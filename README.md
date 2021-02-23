# GCN_res-FLAG
This is an improvement of the [(GCN_res + 8 layers)](https://github.com/ytchx1999/ogbn_arxiv_GCN_res) model, using the FLAG method.

### ogbn-arxiv

+ Check out the model：[(GCN_res + 8 layers)](https://github.com/ytchx1999/ogbn_arxiv_GCN_res)

+ Check out the FLAG method：[FLAG](https://arxiv.org/pdf/2010.09891.pdf)

#### Improvement Strategy：

+ add FLAG method

#### Environmental Requirements

+ pytorch == 1.7.1
+ pytorch_geometric == 1.6.3
+ ogb == 1.2.4

#### Experiment Setup：

The model is 8 layers, 10 runs which conclude 500 epochs.

```bash
python ogbn_gcn_res_flag.py
```

#### Detailed Hyperparameter:

```bash
num_layers = 8
hidden_dim = 128
dropout = 0.5
lr = 0.01
runs = 10
epochs = 500
alpha = 0.2
beta = 0.7
```

#### Result:

```bash
All runs:
Highest Train: 78.61 ± 0.49
Highest Valid: 73.89 ± 0.12
  Final Train: 78.44 ± 0.46
   Final Test: 72.76 ± 0.24
```

| Model          | Test Accuracy   | Valid Accuracy  | Parameters | Hardware         |
| -------------- | --------------- | --------------- | ---------- | ---------------- |
| GCN_res + FLAG | 0.7276 ± 0.0024 | 0.7389 ± 0.0012 | 155824     | Tesla T4（16GB） |

