import numpy as np
#@function
def zscore2Ptgt_softmax(f, softmaxscale:float=2, validTgt=None, marginalizemodels:bool=True, marginalizedecis:bool=True, peroutputmodel:bool=True):
    '''
    convert normalized output scores into target probabilities

    Args:
     f (nM,nTrl,nDecis,nY):  normalized accumulated scores
     softmaxscale (float, optional): slope to scale from scores to probabilities.  Defaults to 2.
     validtgtTrl (bool nM,nTrl,nY): which targets are valid in which trials 
     peroutputmode (bool, optional): assume if nM==nY that we have 1 model per output.  Defaults to True.

    Returns:
     Ptgt (nTrl,nY): target probability for each trial (if marginalizemodels and marginalizedecis is True)
    '''

    # fix the nuisance parameters to get per-output per trial score
    # pick the model

    # make 4d->3d for simplicity
    if f.ndim > 3:
        origf = f.copy()
        if f.shape[0] == 1:
            f = f[0,...]
        else:
            if f.shape[0]==f.shape[-1] and peroutputmodel:
                # WARNING: assume that have unique model for each output..
                # WARNING: f must have same mean and scale for this to be valid!!
                f=np.zeros(f.shape[1:])
                for mi in range(origf.shape[0]):
                    f[..., mi]=origf[mi, :, :, mi]
            # else: 
            #     # BODGE: push the model dimension into the decision point dimension
            #     f = np.moveaxis(f,(0,1,2,3),(1,0,2,3)) # (nM,nTrl,nDecis,nY) -> (nTrl,nM,nDecis,nY)
            #     f = np.reshape(f,(f.shape[0],f.shape[1]*f.shape[2],f.shape[3])) # (nTrl,nM,nDecis,nY) -> (nTrl,nM*nDecis,nY)

    elif f.ndim == 2:
        f = f[np.newaxis, :]

    elif f.ndim == 1:
        f = f[np.newaxis, np.newaxis, :]
    # Now : f= ((nM,)nTrl,nDecis,nY)

    if validTgt is None: # get which outputs are used in which trials..
        validTgt = np.any(f != 0, axis=(-4,-2) if f.ndim>3 else -2) # (nTrl,nY)
    elif validTgt.ndim == 1:
        validTgt = validTgt[np.newaxis, :]

    noutcorr = softmax_nout_corr(np.sum(validTgt,-1)) # (nTrl,)
    softmaxscale = softmaxscale * noutcorr #(nTrl,)

    # get the prob each output conditioned on the model
    Ptgteptimdl = softmax(f*softmaxscale[:,np.newaxis,np.newaxis],validTgt) # ((nM,)nTrl,nDecis,nY) 
    
    # multiple models
    if ((marginalizemodels and Ptgteptimdl.ndim > 3 and Ptgteptimdl.shape[0] > 1) or 
        (marginalizedecis and Ptgteptimdl.shape[-2] > 1)): # mulitple decis points 
        # need to remove the nusiance parameters to get per-trial Y-prob
        if marginalizedecis:
            ftgt=np.zeros((Ptgteptimdl.shape[-3], Ptgteptimdl.shape[-1])) # (nTrl,nY)
        else:
            ftgt=np.zeros(Ptgteptimdl.shape[-3:]) # (nTrl,nDecis,nY)

        # compute entropy over outputs for each decision point
        ent = entropy(Ptgteptimdl,-1)

        for ti in range(Ptgteptimdl.shape[-3]): # loop over trials
            # find when hit max-ent decison point for each model
            if marginalizedecis:
                # find max-ent model + decision points
                entti = ent[...,ti,:]
                midx = np.argmax(entti)
                mi, di = np.unravel_index(midx, entti.shape)
                wght = np.zeros(entti.shape) # (nM,nDecis)
                wght[mi,di:] = 1
                # BODGE 1: just do weighted sum over decis points with more data than max-ent point
                ftgt[ti, :] = np.dot(wght.ravel(), f[..., ti, :, :].reshape((-1,f.shape[-1]))) / np.sum(wght.ravel())
            else:
                # find max-ent model for each decision point
                for di in range(f.shape[-2]):
                    # BODGE 0: use the summed entropy *up to* this decision point to smooth the model selection
                    mi = np.argmax(np.sum(ent[...,ti,:di],-1))
                    # BODGE 1: just take the max-ent model for this decision point
                    ftgt[ti, di, :] = f[mi, ti, di, :]

        # TODO: make this more elegant for matching of the softmax scale
        if ftgt.ndim==3:
            Ptgt = softmax(softmaxscale[:,np.newaxis,np.newaxis]*ftgt,validTgt)
        else:
            Ptgt = softmax(softmaxscale[:,np.newaxis]*ftgt,validTgt)

    else:
        Ptgt = Ptgteptimdl

    if any(np.isnan(Ptgt.ravel())):
        if not all(np.isnan(Ptgt.ravel())):
            print('Error NaNs in target probabilities')
        Ptgt[:] = 0
    return Ptgt


def entropy(p,axis=-1):
    ent = np.sum(p*np.log(np.maximum(p, 1e-08)), axis) # / -np.log(Ptgtepmdl.shape[-1]) # (nDecis)
    return ent


def softmax(f,validTgt=None):
    ''' simple softmax over final dim of input array, with compensation for missing inputs with validTgt mask. '''
    Ptgteptimdl=np.exp(f-np.max(f, -1, keepdims=True)) # (nTrl,nDecis,nY) [ nY x nDecis x nTrl ]
    # cancel out the missing outputs
    if validTgt is not None and not all(validTgt.ravel()):
        Ptgteptimdl = Ptgteptimdl * validTgt[..., np.newaxis, :]
    # convert to softmax, with guard for div by zero
    Ptgteptimdl = Ptgteptimdl / np.maximum(np.sum(Ptgteptimdl, -1, keepdims=True),1e-6)
    return Ptgteptimdl

def softmax_nout_corr(n):
    ''' approximate correction factor for probabilities out of soft-max to correct for number of outputs'''
    #return np.minimum(2.45,1.25+np.log2(np.maximum(1,n))/5.5)/2.45
    return np.ones(n.shape) #np.minimum(2.45,1.25+np.log2(np.maximum(1,n))/5.5)/2.45


def calibrate_softmaxscale(f, validTgt=None, scales=(.5,1,1.5,2,2.5,3,3.5,4,5,7,10,15,20,30), MINP=.01):
    '''
    attempt to calibrate the scale for a softmax decoder to return calibrated probabilities

    Args:
     f (nTrl,nDecis,nY): normalized accumulated scores]
     validTgt(bool nTrl,nY): which targets are valid in which trials
     scales (list:int): set of possible soft-max scales to try
     MINP (float): minimium P-value.  We clip the true-target p-val to this level as a way
            of forcing the fit to concentrate on getting the p-val right when high, rather than
            over penalizing when it's wrong

    Returns:
     softmaxscale (float): slope for softmax to return calibrated probabilities
    '''
    if validTgt is None: # get which outputs are used in which trials..
        validTgt = np.any(f != 0, 1) # (nTrl,nY)
    elif validTgt.ndim == 1:
        validTgt = validTgt[np.newaxis, :]

    # remove trials with no-true-label info
    keep = np.any(f[:, :, 0], (-2, -1)) # [ nTrl ]
    if not np.all(keep):
        Fy = Fy[keep, :, :]
        if validTgt.shape[0] > 1 :
            validTgt = validTgt[keep,:]
 
     # include the nout correction on a per-trial basis
    noutcorr = softmax_nout_corr(np.sum(validTgt,1)) # (nTrl,)

    # simply try a load of scales - as input are normalized shouldn't need more than this
    Ed = np.zeros(len(scales),)
    for i,s in enumerate(scales):
        softmaxscale = s * noutcorr[:,np.newaxis,np.newaxis] #(nTrl,1,1)

        # apply the soft-max with this scaling
        Ptgt = softmax(f*softmaxscale,validTgt)
        # Compute the loss = cross-entropy.  
        # As Y==0 is *always* the true-class, this becomes simply sum log this class 
        Ed[i] = np.sum(-np.log(np.maximum(Ptgt[...,0],MINP)))
        #print("{}) scale={} Ed={}".format(i,s,Ed[i]))
    # use the max-entropy scale
    mini = np.argmin(Ed)
    softmaxscale = scales[mini]
    print("softmaxscale={}".format(softmaxscale))
    return softmaxscale

#@function
def testcase(nY=10, nM=4, nEp=340, nTrl=100, sigstr=.5):
    import numpy as np
    noise = np.random.standard_normal((nM,nTrl,nEp,nY))
    noise = noise - np.mean(noise.ravel())
    noise = noise / np.std(noise.ravel())

    sigamp=sigstr*np.ones(noise.shape[-2]) # [ nEp ]
    # no signal ast the start of the trial
  #startupNoise_samp=nEp*.5;
  #sigamp((1:size(sigamp,2))<startupNoise_samp)=0;
    Fy = np.copy(noise)
    # add the signal
    Fy[0, :, :, 0] = Fy[0, :, :, 0] + sigamp
    #print("Fy={}".format(Fy))
    
    sFy=np.cumsum(Fy,-2)
    from mindaffectBCI.decoder.normalizeOutputScores import normalizeOutputScores
    ssFy,scale_sFy,N,_,_=normalizeOutputScores(Fy,minDecisLen=-1)
    #print('ssFy={}'.format(ssFy.shape))
    from mindaffectBCI.decoder.zscore2Ptgt_softmax import zscore2Ptgt_softmax, softmax
    smax = softmax(ssFy)
    #print("{}".format(smax.shape))
    Ptgt=zscore2Ptgt_softmax(ssFy,marginalizemodels=True, marginalizedecis=False) # (nTrl,nEp,nY)
    #print("Ptgt={}".format(Ptgt.shape))
    import matplotlib.pyplot as plt
    plt.clf()
    tri=1
    plt.subplot(411);plt.cla();
    plt.plot(sFy[0,tri,:,:])
    plt.plot(scale_sFy[0,tri,:],'k')
    plt.title('ssFy')
    plt.grid()
    plt.subplot(412);plt.cla();
    plt.plot(ssFy[0,tri,:,:])
    plt.title('ssFy')
    plt.grid()
    plt.subplot(413);plt.cla()
    plt.plot(smax[0,tri,:,:])
    plt.title('softmax')
    plt.grid()
    plt.subplot(414);plt.cla()
    plt.plot(Ptgt[tri,:,:])
    plt.title('Ptgt')
    plt.grid()
    plt.show()
    
    maxP=np.max(Ptgt,-1) # (nTrl,nEp) [ nEp x nTrl ]
    estopi=[ np.flatnonzero(maxP[tri,:]>.9)[-1] for tri in range(Ptgt.shape[0])]

if __name__=="__main__":
    testcase()
