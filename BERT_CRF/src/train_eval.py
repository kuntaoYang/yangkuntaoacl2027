import argparse
from pathlib import Path
from typing import List
import numpy as np
from tqdm import tqdm
import torch
from torch.utils.data import DataLoader
from transformers import AutoTokenizer
from torch.optim import AdamW

from transformers import get_scheduler

from seqeval.metrics import classification_report

from datasets import read_jsonl, build_label_set, NERDataset, split_train_dev
from model import BertCRF

def collect_word_level(y_pred_ids: List[List[int]], batch_word_ids, id2label):
    """
    将 subword 级别的预测还原到 word 级别：只取每个词的首 subword 的标签。
    """
    batch_preds, batch_mask = [], []
    for pred_ids, word_ids in zip(y_pred_ids, batch_word_ids):
        preds, mask = [], []
        seen = set()
        for pid, wid in zip(pred_ids, word_ids):
            if wid < 0:  # special tokens
                continue
            if wid not in seen:
                preds.append(id2label[pid])
                mask.append(1)
                seen.add(wid)
        batch_preds.append(preds)
        batch_mask.append(mask)
    return batch_preds

def collect_word_level_gold(batch_labels, batch_word_ids, id2label):
    batch_golds = []
    for labels, word_ids in zip(batch_labels, batch_word_ids):
        golds, seen = [], set()
        for lab, wid in zip(labels, word_ids):
            if wid < 0:
                continue
            if wid not in seen:
                golds.append(id2label[int(lab)])
                seen.add(wid)
        batch_golds.append(golds)
    return batch_golds

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_name", default="bert-base-chinese")
    parser.add_argument("--dev_path", default="data/dev.jsonl")
    parser.add_argument("--test_path", default="data/text.jsonl")
    parser.add_argument("--output_dir", default="outputs")
    parser.add_argument("--max_length", type=int, default=256)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--weight_decay", type=float, default=0.01)
    parser.add_argument("--warmup_ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dev_data = read_jsonl(Path(args.dev_path))
    test_data = read_jsonl(Path(args.test_path))

    # 构建标签集（来自 dev + test；若 test 无 labels，不影响）
    labels = build_label_set(dev_data, test_data)
    label2id = {l: i for i, l in enumerate(labels)}
    id2label = {i: l for l, i in label2id.items()}

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, use_fast=True)

    # 训练/验证切分（只有 dev.jsonl 时使用随机切分）
    train_split, valid_split = split_train_dev(dev_data, dev_ratio=0.1, seed=args.seed)

    train_ds = NERDataset(train_split, tokenizer, label2id, max_length=args.max_length)
    valid_ds = NERDataset(valid_split, tokenizer, label2id, max_length=args.max_length)
    test_ds  = NERDataset(test_data,  tokenizer, label2id, max_length=args.max_length)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    valid_loader = DataLoader(valid_ds, batch_size=args.batch_size, shuffle=False)
    test_loader  = DataLoader(test_ds,  batch_size=args.batch_size, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = BertCRF(args.model_name, num_labels=len(labels)).to(device)

    # 优化器与 scheduler
    no_decay = ["bias", "LayerNorm.weight"]
    param_groups = [
        {"params": [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)], "weight_decay": args.weight_decay},
        {"params": [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)], "weight_decay": 0.0},
    ]
    optimizer = AdamW(param_groups, lr=args.lr)

    num_training_steps = args.epochs * len(train_loader)
    num_warmup = int(num_training_steps * args.warmup_ratio)
    scheduler = get_scheduler(
    name="linear",  # 你可以选择 "linear", "cosine", 或其他调度策略
    optimizer=optimizer,
    num_warmup_steps=num_warmup,
    num_training_steps=num_training_steps
)


    best_f1, best_path = -1.0, output_dir / "best.ckpt"

    # 训练 + 验证
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch in tqdm(train_loader, desc=f"Epoch {epoch} / {args.epochs}"):
            for k in batch:
                batch[k] = batch[k].to(device)
            loss, _ = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                token_type_ids=batch["token_type_ids"],
                labels=batch["labels"],
                crf_mask=batch["crf_mask"]
            )
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            losses.append(loss.item())
        print(f"[Train] epoch={epoch} loss={np.mean(losses):.4f}")

        # 验证
        model.eval()
        all_preds, all_golds = [], []
        with torch.no_grad():
            for batch in valid_loader:
                word_ids_cpu = batch["word_ids"].tolist()
                for k in batch:
                    batch[k] = batch[k].to(device)
                emissions = model(
                    input_ids=batch["input_ids"],
                    attention_mask=batch["attention_mask"],
                    token_type_ids=batch["token_type_ids"]
                )
                preds_ids = model.decode(emissions, batch["crf_mask"])
                # 还原到 word-level
                word_preds = collect_word_level(preds_ids, word_ids_cpu, id2label)
                word_golds = collect_word_level_gold(batch["labels"].tolist(), word_ids_cpu, id2label)
                all_preds.extend(word_preds)
                all_golds.extend(word_golds)

        report = classification_report(all_golds, all_preds, digits=4)
        print("[Valid]\n" + report)
        # 从报告中粗取 F1（也可以用 seqeval.f1_score）
        try:
            from seqeval.metrics import f1_score
            f1 = f1_score(all_golds, all_preds)
        except Exception:
            f1 = 0.0

        if f1 > best_f1:
            best_f1 = f1
            torch.save({"model_state": model.state_dict(), "labels": labels}, best_path)
            print(f"✅ 保存最佳模型到: {best_path} (F1={best_f1:.4f})")

    # 测试集评估（使用最佳权重）
    ckpt = torch.load(best_path, map_location=device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()

    all_preds, all_golds = [], []
    with torch.no_grad():
        for batch in DataLoader(test_ds, batch_size=args.batch_size):
            word_ids_cpu = batch["word_ids"].tolist()
            for k in batch:
                batch[k] = batch[k].to(device)
            emissions = model(
                input_ids=batch["input_ids"],
                attention_mask=batch["attention_mask"],
                token_type_ids=batch["token_type_ids"]
            )
            preds_ids = model.decode(emissions, batch["crf_mask"])
            word_preds = collect_word_level(preds_ids, word_ids_cpu, id2label)
            word_golds = collect_word_level_gold(batch["labels"].tolist(), word_ids_cpu, id2label) \
                         if "labels" in test_data[0] else None
            all_preds.extend(word_preds)
            if word_golds is not None:
                all_golds.extend(word_golds)

    if all_golds:
        print("[Test]\n" + classification_report(all_golds, all_preds, digits=4))
    else:
        print("[Test] 文件未提供 gold 标签，已输出预测到:", output_dir / "test_preds.txt")
    # 保存逐句预测
    with open(output_dir / "test_preds.txt", "w", encoding="utf-8") as f:
        for sent in all_preds:
            f.write(" ".join(sent) + "\n")

if __name__ == "__main__":
    main()
