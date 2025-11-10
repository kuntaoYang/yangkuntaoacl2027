import json
from pathlib import Path
from typing import List, Dict, Tuple
import torch
from torch.utils.data import Dataset
from transformers import PreTrainedTokenizerBase

def read_jsonl(path: Path) -> List[Dict]:
    data = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data.append(json.loads(line))
    return data

def build_label_set(*splits: List[Dict]) -> List[str]:
    labels = set(["O"])
    for split in splits:
        for ex in split:
            if "labels" in ex:
                labels.update(ex["labels"])
    # BIO 标签按字典序基本可，但保持 O 在第一个
    labels = sorted([l for l in labels if l != "O"])
    return ["O"] + labels

class NERDataset(Dataset):
    """
    期望每行格式：
    {"tokens": ["我","爱","北","京"], "labels": ["O","O","B-LOC","I-LOC"]}
    """
    def __init__(
        self,
        examples: List[Dict],
        tokenizer: PreTrainedTokenizerBase,
        label2id: Dict[str, int],
        max_length: int = 256
    ):
        self.examples = examples
        self.tokenizer = tokenizer
        self.label2id = label2id
        self.id2label = {v: k for k, v in label2id.items()}
        self.max_length = max_length

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        item = self.examples[idx]
        tokens: List[str] = item["tokens"]
        labels: List[str] = item.get("labels", ["O"] * len(tokens))

        encoding = self.tokenizer(
            tokens,
            is_split_into_words=True,
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_offsets_mapping=False,
            return_tensors="pt"
        )

        # 将 word-level 标签对齐到 subword；只给每个词的首 subword 赋原标签，其余 subword 赋 "O"
        word_ids = encoding.word_ids(batch_index=0)
        label_ids = []
        prev_word_id = None
        for wi in word_ids:
            if wi is None:
                label_ids.append(-1)  # special tokens: 之后 mask 掉
            else:
                if wi != prev_word_id:
                    lab = labels[wi] if wi < len(labels) else "O"
                    label_ids.append(self.label2id.get(lab, self.label2id["O"]))
                else:
                    # 非首 subword：这里给 O（CRF 需要完整序列标签；评估时再只取首 subword）
                    label_ids.append(self.label2id["O"])
            prev_word_id = wi

        # attention mask
        attention_mask = encoding["attention_mask"][0]
        input_ids = encoding["input_ids"][0]
        token_type_ids = encoding.get("token_type_ids", torch.zeros_like(input_ids))

        # CRF 的 mask：True 表示有效 token（非 padding）
        crf_mask = attention_mask.bool()

        labels_tensor = torch.tensor(label_ids, dtype=torch.long)
        return {
            "input_ids": input_ids,
            "token_type_ids": token_type_ids,
            "attention_mask": attention_mask,
            "labels": labels_tensor,
            "crf_mask": crf_mask,
            "word_ids": torch.tensor([-1 if w is None else w for w in word_ids], dtype=torch.long)
        }

def split_train_dev(data: List[Dict], dev_ratio: float = 0.1, seed: int = 42) -> Tuple[List[Dict], List[Dict]]:
    import random
    rnd = random.Random(seed)
    idx = list(range(len(data)))
    rnd.shuffle(idx)
    n_dev = max(1, int(len(data) * dev_ratio))
    dev_idx = set(idx[:n_dev])
    train, dev = [], []
    for i, ex in enumerate(data):
        (dev if i in dev_idx else train).append(ex)
    return train, dev
