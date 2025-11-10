# BERT+CRF 中文 NER（适配 dev.jsonl + text.jsonl）

## 快速开始
```bash
pip install -r requirements.txt

# 训练 + 验证（自动将 dev.jsonl 划分 train/valid）+ 在 text.jsonl 上测试
python src/train_eval.py
```



可选预测：

```
python src/predict.py --sentence "北 京 是 中 国 的 首 都"
```

## 数据格式

每行一条样本：

```
{"tokens": ["我","爱","北","京"], "labels": ["O","O","B-LOC","I-LOC"]}
---

## 说明与小贴士
- **仅有 dev.jsonl 与 text.jsonl**：脚本会自动对 `dev.jsonl` 做 9:1 随机切分训练/验证；`text.jsonl` 用作测试。如果 `text.jsonl` 没有 `labels` 字段，会跳过测试集打分，只输出预测序列到 `outputs/test_preds.txt`。
- **子词对齐**：评估时只在每个词的**首 subword**处取预测，保证与原标签序列对齐。
- **常见错误**：若报 `CUDA out of memory`，把 `--batch_size` 降低或把 `--max_length` 调小；若无显卡，CPU 也能跑，但会慢一些。
- **更换预训练模型**：`--model_name` 可改为如 `hfl/chinese-bert-wwm-ext`、`hfl/chinese-roberta-wwm-ext` 等。
```