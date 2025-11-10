import argparse
from transformers import AutoTokenizer
import torch
from model import BertCRF
from datasets import NERDataset

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_name", default="bert-base-chinese")
    parser.add_argument("--ckpt", default="outputs/best.ckpt")
    parser.add_argument("--sentence", required=True, help="用空格分词或按字切分：例：北 京 是 中 国 的 首 都")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(args.ckpt, map_location=device)
    labels = ckpt["labels"]
    label2id = {l: i for i, l in enumerate(labels)}
    id2label = {i: l for l, i in label2id.items()}

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, use_fast=True)
    model = BertCRF(args.model_name, num_labels=len(labels)).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    tokens = args.sentence.strip().split()
    ex = {"tokens": tokens, "labels": ["O"] * len(tokens)}
    ds = NERDataset([ex], tokenizer, label2id)
    batch = ds[0]
    for k in batch:
        batch[k] = batch[k].unsqueeze(0).to(device)

    with torch.no_grad():
        emissions = model(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            token_type_ids=batch["token_type_ids"]
        )
        pred_ids = model.decode(emissions, batch["crf_mask"])[0]

    # 取首 subword 的预测（datasets 里 word_ids 已处理）
    word_ids = batch["word_ids"][0].tolist()
    out = []
    seen = set()
    for pid, wid in zip(pred_ids, word_ids):
        if wid < 0: 
            continue
        if wid not in seen:
            out.append(id2label[pid]); seen.add(wid)
    print(list(zip(tokens, out)))

if __name__ == "__main__":
    main()
