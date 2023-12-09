# import argparse
from util import *
from torch.utils.data import DataLoader, RandomSampler, SequentialSampler, Dataset
import os
import pickle
import torch
from torch.nn.utils.rnn import pad_sequence
import pdb

def data_perpare(args,mode,tokenizer,data=None):
    """
    Prepare the data for training or evaluation.

    Args:
        args (object): The arguments object.
        mode (str): The mode, either 'train' or 'eval'.
        tokenizer (object): The tokenizer object.
        data (list, optional): The data to be used. Defaults to None.

    Returns:
        dataset (object): The dataset object.
        sampler (object): The sampler object.
        dataloader (object): The dataloader object.
    """
    dataset=TSNote_Irg(args,mode, tokenizer,data=data)
    if mode=='train':
        sampler = RandomSampler(dataset)
        dataloader= DataLoader(dataset, sampler=sampler, batch_size=args.train_batch_size,collate_fn=TextTSIrgcollate_fn)
    else:
        sampler = SequentialSampler(dataset)
        dataloader= DataLoader(dataset, sampler=sampler, batch_size=args.eval_batch_size,collate_fn=TextTSIrgcollate_fn)


    return dataset, sampler, dataloader


def F_impute(X,tt,mask,duration,tt_max):
    """
    Imputes missing values in the input data based on the discretization rule mentioned in the paper.

    Parameters:
    X (numpy.ndarray): Input data matrix of shape (n_samples, n_features).
    tt (numpy.ndarray): Array of time values corresponding to each sample.
    mask (numpy.ndarray): Array indicating missing values in the input data.
    duration (int): Duration of each time interval for discretization.
    tt_max (int): Maximum time value.

    Returns:
    numpy.ndarray: Imputed data matrix of shape (tt_max//duration, n_features*2).
    """
    
    no_feature=X.shape[1]
    impute=np.zeros(shape=(tt_max//duration,no_feature*2))
    for  x,t,m in zip(X,tt,mask):
        row=int(t/duration)
        if row>=tt_max:
            continue
        for  f_idx, (rwo_x, row_m) in enumerate(zip(x,m)):
            # perform imputation according to the discretization rule in paper
            if row_m==1:
                impute[row][no_feature+f_idx]=1
                impute[row][f_idx]=rwo_x
            else:
                if impute[row-1][f_idx]!=0:
                    impute[row][f_idx]=impute[row-1][f_idx]

    return impute


class TSNote_Irg(Dataset):
    """
    A PyTorch dataset class for handling time series note data in the MIMIC-IV dataset.

    Args:
        args (argparse.Namespace): The command-line arguments.
        mode (str): The mode of the dataset (e.g., "train", "val", "test").
        tokenizer (transformers.PreTrainedTokenizer): The tokenizer for encoding the text data.
        data (list, optional): The list of data samples. If not provided, the data will be loaded from a file.

    Attributes:
        tokenizer (transformers.PreTrainedTokenizer): The tokenizer for encoding the text data.
        max_len (int): The maximum length of the input sequences.
        data (list): The list of data samples.
        chunk (bool): Whether to chunk the data.
        text_id_attn_data (list): The list of text data samples for attention calculation.
        padding (str): The padding strategy for the input sequences.
        notes_order (str): The order of the notes.
        order_sample (numpy.ndarray): The array of randomly sampled note orders.
        modeltype (str): The type of the model.
        model_name (str): The name of the model.
        num_of_notes (int): The number of notes to consider.
        tt_max (float): The maximum value of the time-to-end feature.

    Methods:
        __getitem__(self, idx): Retrieves the data at the given index.
        __len__(self): Returns the length of the dataset.
    """
    
    def __init__(self,args,mode,tokenizer,data=None):
        self.tokenizer = tokenizer
        self.max_len = args.max_length
        if data !=None:
            self.data=data
        else:
            self.data =load_data(file_path=args.file_path,mode=mode,debug=args.debug,task=args.task)
        self.chunk=args.chunk
        if self.chunk:
            self.text_id_attn_data = load_data(file_path=args.file_path,mode=mode,text=True, task=args.task)
        self.padding= "max_length" if args.pad_to_max_length  else False

        if mode=="train":
            self.notes_order=args.notes_order
        else:
            self.notes_order="Last"

        if args.ratio_notes_order!=None:
            self.order_sample=np.random.binomial(1, args.ratio_notes_order,len(self.data))

        self.modeltype=args.modeltype
        self.model_name=args.model_name
        self.num_of_notes=args.num_of_notes
        self.tt_max=args.tt_max
        self.reg_ts = args.reg_ts
        
    def __getitem__(self, idx):
        """
        Retrieves the data at the given index.

        Args:
            idx (int): The index of the data to retrieve.

        Returns:
            dict: A dictionary containing the data at the given index.
        """
        if self.notes_order!=None:

            notes_order=self.notes_order
        else:
            # notes_order= 'Last' if self.order_sample[idx]==1  else 'First'
            notes_order = 'Last'

        data_detail = self.data[idx]
        idx=data_detail['name']
        reg_ts=data_detail['reg_ts']
        ts=data_detail['irg_ts']

        ts_mask=data_detail['irg_ts_mask']
        
        if 'text_data' not in data_detail.keys():
            text = ""
        else:
            text = data_detail['text_data']
            text_time_to_end=data_detail["text_time_to_end"]

        # if len(text)==0:
        #     return None
        text_token=[]
        atten_mask=[]
        label=data_detail["label"]
        ts_tt=data_detail["ts_tt"]

        # reg_ts = data_detail['reg_ts']

        if self.reg_ts:
            reg_ts=F_impute(ts,ts_tt,ts_mask,1,self.tt_max)
            reg_ts=torch.tensor(reg_ts,dtype=torch.float)
        else:
            reg_ts=None
        
        if 'Text' in self.modeltype :
            for t in text:
                inputs = self.tokenizer.encode_plus(t, padding=self.padding,\
                                                    max_length=self.max_len,\
                                                    add_special_tokens=True,\
                                                    return_attention_mask = True,\
                                                    truncation=True)
                text_token.append(torch.tensor(inputs['input_ids'],dtype=torch.long))
                attention_mask=inputs['attention_mask']
                if "Longformer" in self.model_name :

                    attention_mask[0]+=1
                    atten_mask.append(torch.tensor(attention_mask,dtype=torch.long))
                else:
                    atten_mask.append(torch.tensor(attention_mask,dtype=torch.long))
        
        if 'CXR' in self.modeltype:
            cxr_feats = data_detail['cxr_feats']
            cxr_feats = torch.tensor(cxr_feats, dtype=torch.float)

            cxr_time_to_end = data_detail['cxr_time'].astype(np.float32)
            cxr_time_to_end = torch.tensor(cxr_time_to_end, dtype=torch.float)

            cxr_time_mask = [1] * len(cxr_time_to_end)
            cxr_time_mask = torch.tensor(cxr_time_mask, dtype=torch.long)
        else:
            cxr_feats = None
            cxr_time_to_end = None
            cxr_time_mask = None

        label=torch.tensor(label,dtype=torch.long)
        ts=torch.tensor(ts,dtype=torch.float)
        ts_mask=torch.tensor(ts_mask,dtype=torch.long)
        ts_tt=torch.tensor([t/self.tt_max for t in ts_tt],dtype=torch.float)

        if 'Text' in self.modeltype :
            text_time_to_end=[1-t/self.tt_max for t in text_time_to_end]
            text_time_mask=[1]*len(text_time_to_end)

            while len(text_token)<self.num_of_notes:
                text_token.append(torch.tensor([0],dtype=torch.long))
                atten_mask.append(torch.tensor([0],dtype=torch.long))
                text_time_to_end.append(0)
                text_time_mask.append(0)


            text_time_to_end=torch.tensor(text_time_to_end,dtype=torch.float)
            text_time_mask=torch.tensor(text_time_mask,dtype=torch.long)

        if 'TS_CXR' in self.modeltype:
            return {'idx':idx,'ts':ts, 'ts_mask': ts_mask, 'ts_tt': ts_tt, 'reg_ts':reg_ts,"label":label, 'cxr_feats':cxr_feats, 'cxr_time':cxr_time_to_end, 'cxr_time_mask':cxr_time_mask}
        if 'Text' not in self.modeltype:
            return {'idx':idx,'ts':ts, 'ts_mask': ts_mask, 'ts_tt': ts_tt, 'reg_ts':reg_ts,"label":label}
        if notes_order=="Last":
            return {'idx':idx,'ts':ts, 'ts_mask': ts_mask, 'ts_tt': ts_tt,'reg_ts':reg_ts, "input_ids":text_token[-self.num_of_notes:],"label":label, "attention_mask":atten_mask[-self.num_of_notes:], \
            'note_time':text_time_to_end[-self.num_of_notes:], 'text_time_mask': text_time_mask[-self.num_of_notes:],
               }
        else:
            return {'idx':idx,'ts':ts, 'ts_mask': ts_mask, 'ts_tt': ts_tt, 'reg_ts':reg_ts,"input_ids":text_token[:self.num_of_notes],"label":label, "attention_mask":atten_mask[:self.num_of_notes] ,\
             'note_time':text_time_to_end[:self.num_of_notes],'text_time_mask': text_time_mask[:self.num_of_notes]
               }

    def __len__(self):
        return len(self.data)



def load_data(file_path, mode, debug=False, text=False, task='ihm'):
    """
    Load data from a file.

    Args:
        file_path (str): The path to the file.
        mode (str): The mode of the data.
        debug (bool, optional): Whether to enable debug mode. Defaults to False.
        text (bool, optional): Whether the data is text. Defaults to False.
        task (str, optional): The task of the data. Defaults to 'ihm'.

    Returns:
        data: The loaded data.
    """
    dataPath = os.path.join(file_path, mode + '_' + task + '_stays.pkl')

    if os.path.isfile(dataPath):
        print('Using', dataPath)
        with open(dataPath, 'rb') as f:
            data = pickle.load(f)
            if debug and not text:
                data = data[:100]

    return data


def TextTSIrgcollate_fn(batch):
    """
    Collates a batch of data samples for the TextTSIrg model.

    Args:
        batch (list): A list of data samples, where each sample is a dictionary containing the following keys:
            - 'ts': Time series input sequence
            - 'ts_mask': Mask for the time series input sequence
            - 'ts_tt': Time-to-target sequence
            - 'label': Label for the sample
            - 'reg_ts': Regularized time series input

    Returns:
        tuple: A tuple containing the following tensors:
            - ts_input_sequences: Padded time series input sequences
            - ts_mask_sequences: Padded masks for the time series input sequences
            - ts_tt: Padded time-to-target sequences
            - reg_ts_input: Padded regularized time series inputs
            - input_ids: Padded input IDs (if present in the batch)
            - attn_mask: Padded attention masks (if present in the batch)
            - note_time: Padded note time sequences (if present in the batch)
            - note_time_mask: Padded masks for the note time sequences (if present in the batch)
            - cxr_feats: Padded CXR features (if present in the batch)
            - cxr_time: Padded CXR time sequences (if present in the batch)
            - cxr_time_mask: Padded masks for the CXR time sequences (if present in the batch)
            - label: Stacked labels for the samples
    """

    batch = list(filter(lambda x: x is not None, batch))
    batch = list(filter(lambda x: len(x['ts']) < 1000, batch))
    try:
        ts_input_sequences = pad_sequence([example['ts'] for example in batch], batch_first=True, padding_value=0)
        ts_mask_sequences = pad_sequence([example['ts_mask'] for example in batch], batch_first=True, padding_value=0)
        ts_tt = pad_sequence([example['ts_tt'] for example in batch], batch_first=True, padding_value=0)
        label = torch.stack([example["label"] for example in batch])
        reg_ts_input = torch.stack([example['reg_ts'] for example in batch])
    except:
        return

    if 'input_ids' in batch[0].keys():
        input_ids = [pad_sequence(example['input_ids'], batch_first=True, padding_value=0).transpose(0, 1) for example in batch]
        attn_mask = [pad_sequence(example['attention_mask'], batch_first=True, padding_value=0).transpose(0, 1) for example in batch]

        input_ids = pad_sequence(input_ids, batch_first=True, padding_value=0).transpose(1, 2)
        attn_mask = pad_sequence(attn_mask, batch_first=True, padding_value=0).transpose(1, 2)

        note_time = pad_sequence([torch.tensor(example['note_time'], dtype=torch.float) for example in batch], batch_first=True, padding_value=0)
        note_time_mask = pad_sequence([torch.tensor(example['text_time_mask'], dtype=torch.long) for example in batch], batch_first=True, padding_value=0)
    else:
        input_ids, attn_mask, note_time, note_time_mask = None, None, None, None
    
    if 'cxr_feats' in batch[0].keys():
        cxr_feats = [pad_sequence(example['cxr_feats'], batch_first=True, padding_value=0) for example in batch]
        cxr_feats = pad_sequence(cxr_feats, batch_first=True, padding_value=0)
        cxr_time = pad_sequence([torch.tensor(example['cxr_time'], dtype=torch.float) for example in batch], batch_first=True, padding_value=0)
        cxr_time_mask = pad_sequence([torch.tensor(example['cxr_time_mask'], dtype=torch.long) for example in batch], batch_first=True, padding_value=0)
    else:
        cxr_feats, cxr_time, cxr_time_mask = None, None, None

    return ts_input_sequences, ts_mask_sequences, ts_tt, reg_ts_input, \
         input_ids, attn_mask, note_time, note_time_mask, cxr_feats, cxr_time, cxr_time_mask, label
def TextTSIrgcollate_fn(batch):

    batch = list(filter(lambda x: x is not None, batch))
    batch = list(filter(lambda x: len(x['ts']) <1000, batch))
    try:
        ts_input_sequences=pad_sequence([example['ts'] for example in batch],batch_first=True,padding_value=0 )
        ts_mask_sequences=pad_sequence([example['ts_mask'] for example in batch],batch_first=True,padding_value=0 )
        ts_tt=pad_sequence([example['ts_tt'] for example in batch],batch_first=True,padding_value=0 )
        label=torch.stack([example["label"] for example in batch])

        if batch[0]['reg_ts'] is not None:
            reg_ts_input=torch.stack([example['reg_ts'] for example in batch])
        else:
            reg_ts_input=None
    except:
        return 

    if 'input_ids' in batch[0].keys():
        input_ids=[pad_sequence(example['input_ids'],batch_first=True,padding_value=0).transpose(0,1) for example in batch]
        attn_mask=[pad_sequence(example['attention_mask'],batch_first=True,padding_value=0).transpose(0,1) for example in batch]

        input_ids=pad_sequence(input_ids,batch_first=True,padding_value=0).transpose(1,2)
        attn_mask=pad_sequence(attn_mask,batch_first=True,padding_value=0).transpose(1,2)

        note_time=pad_sequence([torch.tensor(example['note_time'],dtype=torch.float) for example in batch],batch_first=True,padding_value=0)
        note_time_mask=pad_sequence([torch.tensor(example['text_time_mask'],dtype=torch.long) for example in batch],batch_first=True,padding_value=0)
    else:
        input_ids,attn_mask, note_time, note_time_mask =None,None,None,None
    
    if 'cxr_feats' in batch[0].keys():
        # cxr_feats=pad_sequence([example['cxr_feats'] for example in batch],batch_first=True,padding_value=0 )
        cxr_feats=[pad_sequence(example['cxr_feats'],batch_first=True,padding_value=0) for example in batch]
        cxr_feats=pad_sequence(cxr_feats,batch_first=True,padding_value=0)
        cxr_time=pad_sequence([torch.tensor(example['cxr_time'],dtype=torch.float) for example in batch],batch_first=True,padding_value=0)
        cxr_time_mask=pad_sequence([torch.tensor(example['cxr_time_mask'],dtype=torch.long) for example in batch],batch_first=True,padding_value=0)
    else:
        cxr_feats, cxr_time, cxr_time_mask = None, None, None

    return ts_input_sequences,ts_mask_sequences, ts_tt, reg_ts_input, \
         input_ids,attn_mask, note_time ,note_time_mask, cxr_feats, cxr_time, cxr_time_mask, label




