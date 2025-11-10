import torch
import torch.nn as nn
from transformers import AutoModel
from torchcrf import CRF

class BertCRF(nn.Module):
    def __init__(self, model_name: str, num_labels: int, dropout: float = 0.1):
        super().__init__()
        self.bert = AutoModel.from_pretrained(model_name)
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(self.bert.config.hidden_size, num_labels)
        # batch_first=True: 发/收的张量形状 [batch, seq, num_labels]
        self.crf = CRF(num_tags=num_labels, batch_first=True)

    def forward(self, input_ids, attention_mask, token_type_ids, labels=None, crf_mask=None):
        outputs = self.bert(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids
        )
        seq_output = self.dropout(outputs.last_hidden_state)
        emissions = self.classifier(seq_output)  # [B, L, C]

        if labels is not None:
            # CRF 期望 mask 为 byte/bool；负对数似然（要最大化 log_likelihood，所以取负号）
            log_likelihood = self.crf(emissions, labels, mask=crf_mask, reduction='mean')
            loss = -log_likelihood
            return loss, emissions
        else:
            return emissions

    def decode(self, emissions, crf_mask):
        # 返回 List[List[int]]（每条序列的标签 id 序列）
        return self.crf.decode(emissions, mask=crf_mask)
