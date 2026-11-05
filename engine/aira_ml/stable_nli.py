"""Research-only deterministic-per-input adapter; original model bytes untouched."""
import numpy as np
from tokenizers import Tokenizer

class StableNli:
    def __init__(self, original):
        self.sess=original.sess
        self.names=original.names
        self.tok=Tokenizer.from_str(original.tok.to_str())
        self.tok.no_padding()
        self.tok.enable_truncation(256)
        self.calls=0

    def run(self, a, b=None, bs=32):
        if b is None or len(a)!=len(b):
            raise ValueError('NLI requires equally sized premise/hypothesis sequences')
        if not isinstance(bs,int) or bs<=0:
            raise ValueError('bs must be positive; inference remains per direction')
        out=[]
        for premise,hypothesis in zip(a,b):
            enc=self.tok.encode(premise,hypothesis)
            feed={'input_ids':np.array([enc.ids],np.int64),
                  'attention_mask':np.array([enc.attention_mask],np.int64),
                  'token_type_ids':np.array([enc.type_ids],np.int64)}
            out.append(self.sess.run(None,{k:v for k,v in feed.items() if k in self.names})[0])
            self.calls+=1
        width=self.sess.get_outputs()[0].shape[-1]
        return np.concatenate(out) if out else np.zeros((0,width),np.float32)
