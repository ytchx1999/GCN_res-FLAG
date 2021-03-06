import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np

from torch_geometric.nn import GCNConv, GATConv, SAGEConv, JumpingKnowledge
from torch_geometric.data import NeighborSampler
import torch_geometric.transforms as T
from torch_geometric.nn import PairNorm

from ogb.nodeproppred import PygNodePropPredDataset, Evaluator

from logger import Logger
from attacks import *

import argparse

"""
批处理：full-batch
图数据表示方法：SpMM
模型：GCN_res + FLAG
数据集：ogbn-arxiv
"""

# 加载数据集
dataset = PygNodePropPredDataset(
    name='ogbn-arxiv', root='./arxiv/', transform=T.ToSparseTensor())
# dataset = PygNodePropPredDataset(name='ogbn-products', root='./products/', transform=T.ToSparseTensor())
print(dataset)
data = dataset[0]
print(data)

# 划分数据集
split_idx = dataset.get_idx_split()

# 定义评估器
evaluator = Evaluator(name='ogbn-arxiv')
# evaluator = Evaluator(name='ogbn-products')

train_idx = split_idx['train']
test_idx = split_idx['test']


# 定义网络
# GCN
class GCNNet(nn.Module):
    def __init__(self, dataset, hidden=256, num_layers=3):
        """
        :param dataset: 数据集
        :param hidden: 隐藏层维度，默认256
        :param num_layers: 模型层数，默认为3
        """
        super(GCNNet, self).__init__()

        self.num_layers = num_layers
        self.convs = nn.ModuleList()
        self.bns = nn.ModuleList()

        self.convs.append(GCNConv(dataset.num_node_features, hidden))
        self.bns.append(nn.BatchNorm1d(hidden))

        for i in range(self.num_layers - 2):
            self.convs.append(GCNConv(hidden, hidden))
            self.bns.append(nn.BatchNorm1d(hidden))

        self.convs.append(GCNConv(hidden, dataset.num_classes))

    def reset_parameters(self):
        for conv in self.convs:
            conv.reset_parameters()
        for bn in self.bns:
            bn.reset_parameters()

    def forward(self, data):
        x, adj_t = data.x, data.adj_t

        for i in range(self.num_layers - 1):
            x = self.convs[i](x, adj_t)
            x = self.bns[i](x)  # 小数据集不norm反而效果更好
            x = F.relu(x)
            x = F.dropout(x, p=0.5, training=self.training)

        x = self.convs[-1](x, adj_t)
        x = F.log_softmax(x, dim=1)

        return x


# GCN_res
class GCN_res(nn.Module):
    def __init__(self, dataset, hidden=256, num_layers=6):
        super(GCN_res, self).__init__()

        self.num_layers = num_layers
        self.convs = nn.ModuleList()
        self.bns = nn.ModuleList()

        self.input_fc = nn.Linear(dataset.num_node_features, hidden)

        for i in range(self.num_layers):
            self.convs.append(GCNConv(hidden, hidden))
            self.bns.append(nn.BatchNorm1d(hidden))

        self.out_fc = nn.Linear(hidden, dataset.num_classes)
        self.weights = torch.nn.Parameter(torch.randn((len(self.convs))))

    def reset_parameters(self):
        for conv in self.convs:
            conv.reset_parameters()
        for bn in self.bns:
            bn.reset_parameters()
        self.input_fc.reset_parameters()
        self.out_fc.reset_parameters()
        torch.nn.init.normal_(self.weights)

    def forward(self, x, adj_t):

        x = self.input_fc(x)
        x_input = x  # .copy()

        layer_out = []  # 保存每一层的结果
        for i in range(self.num_layers):
            x = self.convs[i](x, adj_t)
            x = self.bns[i](x)
            x = F.relu(x, inplace=True)
            x = F.dropout(x, p=0.5, training=self.training)

            if i == 0:
                x = x + 0.2 * x_input
            else:
                x = x + 0.2 * x_input + 0.7 * layer_out[i - 1]
            layer_out.append(x)

        weight = F.softmax(self.weights, dim=0)
        for i in range(len(layer_out)):
            layer_out[i] = layer_out[i] * weight[i]

        x = sum(layer_out)
        x = self.out_fc(x)
        x = F.log_softmax(x, dim=1)

        return x


# 定义解析的参数
parser = argparse.ArgumentParser(description='OGBN-Arxiv (GNN)')
parser.add_argument('--step-size', type=float, default=1e-3)
parser.add_argument('-m', type=int, default=3)

args = parser.parse_args()

# 实例化模型
# model = GCNNet(dataset=dataset, hidden=256, num_layers=3)
model = GCN_res(dataset=dataset, hidden=128, num_layers=8)
print(model)

# 转换为cpu或cuda格式
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(device)
model.to(device)
data = data.to(device)
data.adj_t = data.adj_t.to_symmetric()  # 对称归一化
train_idx = train_idx.to(device)

# 定义损失函数和优化器
criterion = nn.NLLLoss().to(device)
optimizer = optim.Adam(model.parameters(), lr=0.01)


# 定义训练函数
def train():
    model.train()

    out = model(data.x, data.adj_t)
    loss = criterion(out[train_idx], data.y.squeeze(1)[train_idx])

    optimizer.zero_grad()
    loss.backward()
    optimizer.step()

    return loss.item()


# FLAG训练
def train_flag(model, data, train_idx, optimizer, device, args):
    y = data.y.squeeze(1)[train_idx]

    def forward(perturb): return model(data.x + perturb, data.adj_t)[train_idx]

    model_forward = (model, forward)

    loss, _ = flag(model_forward, data.x.shape, y, args, optimizer, device, F.nll_loss)

    return loss.item()


# 定义测试函数
@torch.no_grad()
def test():
    model.eval()

    out = model(data.x, data.adj_t)
    y_pred = out.argmax(dim=-1, keepdim=True)

    train_acc = evaluator.eval({
        'y_true': data.y[split_idx['train']],
        'y_pred': y_pred[split_idx['train']],
    })['acc']
    valid_acc = evaluator.eval({
        'y_true': data.y[split_idx['valid']],
        'y_pred': y_pred[split_idx['valid']],
    })['acc']
    test_acc = evaluator.eval({
        'y_true': data.y[split_idx['test']],
        'y_pred': y_pred[split_idx['test']],
    })['acc']

    return train_acc, valid_acc, test_acc


# 程序入口
if __name__ == '__main__':
    runs = 10
    logger = Logger(runs)

    for run in range(runs):
        print(sum(p.numel() for p in model.parameters()))
        model.reset_parameters()

        for epoch in range(500):
            loss = train_flag(model, data, train_idx, optimizer, device, args)
            # print('Epoch {:03d} train_loss: {:.4f}'.format(epoch, loss))

            result = test()
            train_acc, valid_acc, test_acc = result
            # print(f'Train: {train_acc:.4f}, Val: {valid_acc:.4f}, 'f'Test: {test_acc:.4f}')
            print(f'Run: {run + 1:02d}, '
                  f'Epoch: {epoch:02d}, '
                  f'Loss: {loss:.4f}, '
                  f'Train: {100 * train_acc:.2f}%, '
                  f'Valid: {100 * valid_acc:.2f}% '
                  f'Test: {100 * test_acc:.2f}%')

            logger.add_result(run, result)

    logger.print_statistics()
