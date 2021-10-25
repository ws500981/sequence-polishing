#train.py
import torch
from argparse import ArgumentParser
from progressbar import ProgressBar
from pytorch_lightning.callbacks import ModelCheckpoint
import pytorch_lightning as pl
import torch.nn.functional as F
import torchmetrics
from THEDataModule import THEDataModule
from pytorch_lightning.callbacks.early_stopping import EarlyStopping
import torch.nn as nn
import numpy as np
import torch.nn.init as init
import math
from pytorch_lightning.loggers import WandbLogger


class THELightningModule(pl.LightningModule):

    def __init__(self, lr, epochs, patience, in_size, hidden_size, num_layers):
        super().__init__()
        #constructor

        # Model 
        self.embedding = nn.Embedding(12, 50)
        self.do = nn.Dropout(0.2)

        self.fc1 = nn.Linear(200, 100)
        self.do1 = nn.Dropout(0.2)

        self.fc2 = nn.Linear(100, 10)
        self.do2 = nn.Dropout(0.2)

        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.in_size = in_size

        # Metrics
        self.train_accuracy = torchmetrics.Accuracy()
        self.val_accuracy = torchmetrics.Accuracy()

        # Hyperparameters
        self.lr = lr
        self.epochs = epochs
        self.patience = patience

        self.gru = nn.GRU(self.in_size, self.hidden_size, num_layers=self.num_layers,
                          batch_first=True, bidirectional=True, dropout=0.2)
        stdv = math.sqrt(2.0 / self.gru.hidden_size)

        for param in self.gru.parameters():
            if len(param.shape) >= 2:
                init.orthogonal_(param.data)
            else:
                init.normal_(param.data)

        self.fc4 = nn.Linear(2 * hidden_size, 5)

    def forward(self, x):
        x = self.do(self.embedding(x))
        x = x.permute((0, 2, 3, 1))

        x = F.relu(self.fc1(x))
        x = self.do1(x)

        x = F.relu(self.fc2(x))
        x = self.do2(x)

        x = x.reshape(-1, 90, self.in_size)
        x, _ = self.gru(x)

        return self.fc4(x)


    def cross_entropy_loss(self, logits, labels):
        return F.cross_entropy(logits, labels)


    def training_step(self, batch, batch_idx):
        x, y = batch
        x = x.long()
        logits = self.forward(x).transpose(1, 2)
        loss = self.cross_entropy_loss(logits, y)
        train_acc_batch = self.train_accuracy(logits, y)
        self.log('train_loss', loss)
        return loss


    def training_epoch_end(self, outputs):
        accuracy = self.train_accuracy.compute()
        self.log('Train_acc_epoch', accuracy, prog_bar=True)


    def validation_step(self, batch, batch_idx):
        x, y = batch
        x = x.long()
        logits = self.forward(x).transpose(1, 2)
        loss = self.cross_entropy_loss(logits, y)
        val_acc_batch = self.val_accuracy(logits, y)
        self.log('val_acc_batch', val_acc_batch, prog_bar=True)
        self.log('val_loss_batch', loss, prog_bar=True)
        return loss


    def validation_epoch_end(self, outputs):
        accuracy = self.val_accuracy.compute()
        self.log('val_acc_epoch', accuracy, prog_bar=True)


    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.lr)
        return optimizer


def main():
    # argument parser
    parser = ArgumentParser()
    parser.add_argument('datapath', type=str) # training set path or test set path
    parser.add_argument('out', type=str) # output file (for train) / directory (for test) path
    parser.add_argument('--valpath', type=str, default=None) # validation set path
    parser.add_argument('--memory', action='store_true', default=False)
    parser.add_argument('--t', type=int, default=0) # number of threads
    parser.add_argument('--b', type=int, default=128) # batch size
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--in_size", type=int, default=500)
    parser.add_argument("--hidden_size", type=int, default=128)
    parser.add_argument("--num_layers", type=int, default=3)
    
    parser = pl.Trainer.add_argparse_args(parser)
    args = parser.parse_args()

    # weights and biases
    wandb_logger = WandbLogger(project='roko', log_model='all')

    # early stopping
    early_stop_callback = EarlyStopping(monitor="val_acc_batch", patience=args.patience)

    # model checkpoint
    checkpoint_callback = ModelCheckpoint(monitor='val_acc_batch', dirpath=args.out, filename='sample-{val_acc_batch:.2f}')
    
    # initialize trainer
    trainer = pl.Trainer.from_argparse_args(args, gpus=[4,5,6,7], track_grad_norm=2, accelerator="ddp", limit_train_batches=100, limit_val_batches=100, logger=wandb_logger, callbacks=[early_stop_callback, checkpoint_callback])
    
    # data
    data = THEDataModule(args.datapath, args.b, args.memory, args.valpath, args.t)

    # Instantiate model
    model = THELightningModule(lr=args.lr, epochs=args.epochs, patience=args.patience, in_size=args.in_size, hidden_size=args.hidden_size, num_layers=args.num_layers)

    wandb_logger.watch(model)

    trainer.fit(model, datamodule=data)


if __name__ == "__main__":
    main()