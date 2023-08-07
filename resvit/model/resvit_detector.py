import os
from typing import Any, Optional
from lightning.pytorch.utilities.types import STEP_OUTPUT
import torch
import torch.nn as nn
from resvit.module.enc_dec import build_enc_dec
from resvit.module.bottleneck import build_bottleneck
from resvit.utils.dataset import ResViTDetectorDataset
from resvit.module.loss import BalanceBCELoss, DiceLoss
from torcheval.metrics.functional import binary_precision, binary_recall, binary_f1_score
from omegaconf import DictConfig
import lightning.pytorch as pl


class ResViTDetector(pl.LightningModule):
    def __init__(self, cfg: DictConfig):
        super(ResViTDetector, self).__init__()
        
        self.encoder, self.decoder, _ = build_enc_dec(cfg.enc_dec, out_layer=False)
        self.bottleneck = build_bottleneck(cfg.bottleneck)

        if os.path.isfile(cfg.pretrain):
            pretrain = torch.load(cfg.pretrain, map_location=self.device)['state_dict']
            self.load_state_dict(pretrain, strict=False)
        
        self.out = nn.Sequential(
            nn.Conv2d(
                in_channels=cfg.enc_dec.in_channels,
                out_channels=cfg.enc_dec.in_channels,
                kernel_size=3,
                stride=1,
                padding=1,
            ),
            nn.Sigmoid()
        )
           
        # self.prob_producer = nn.Sequential(
        #     nn.Conv2d(
        #         in_channels=cfg.enc_dec.in_channels,
        #         out_channels=cfg.enc_dec.in_channels,
        #         kernel_size=3,
        #         stride=1,
        #         padding=1,
        #     ),
        #     nn.Sigmoid()
        # )
        
        # self.thres_producer = nn.Sequential(
        #     nn.Conv2d(
        #         in_channels=cfg.enc_dec.in_channels,
        #         out_channels=cfg.enc_dec.in_channels,
        #         kernel_size=3,
        #         stride=1,
        #         padding=1,
        #     ),
        #     nn.Sigmoid()
        # )
        
        self.loss = {
            'ls': nn.BCELoss(),
            'lb': DiceLoss(),
            'lt': nn.L1Loss(),
        }
        
        self.train_dataset = ResViTDetectorDataset(cfg.train_dataset)
        self.validation_dataset = ResViTDetectorDataset(cfg.validation_dataset)
        self.test_dataset = ResViTDetectorDataset(cfg.test_dataset)
        
        self.optimizer = torch.optim.AdamW(
            params=self.parameters(),
            lr=cfg.optim.lr,
            betas=cfg.optim.betas,
            weight_decay=cfg.optim.weight_decay,
        )
        
    def forward(self, x):
        x = self.encoder(x)
        x = self.bottleneck(x)
        x = self.decoder(x, self.encoder.layers_outs)
        x = self.out(x)
        # prob = self.prob_producer(x)
        # thres = self.thres_producer(x)
        # bit = 1 / (1 + torch.exp(-50 * (prob - thres)))
        return x
    
    def training_step(self, batch, batch_idx):
        x, gt = batch
        
        x_pred = self.forward(x)
        
        loss = self.loss['ls'](x_pred, gt) + self.loss['lb'](x_pred, gt)
        
        self.log("train_loss", loss, on_step=True, on_epoch=True, prog_bar=True, logger=True)
        self.log("lr", self.optimizer.get_last_lr(), on_step=True, on_epoch=True, prog_bar=True, logger=True)

        return loss
    
    def validation_step(self, batch, batch_idx):
        x, gt = batch
        
        x_pred = self.forward(x)
        loss = self.loss['ls'](x_pred, gt) + self.loss['lb'](x_pred, gt)
        x_pred = (x_pred > 0.5) * 1.0
        precision = binary_precision(x_pred, gt)
        recall = binary_recall(x_pred, gt)
        f1 = binary_f1_score(x_pred, gt)
        
        self.log("train_loss", loss, on_step=True, on_epoch=True, prog_bar=True, logger=True)
        self.log("lr", self.optimizer.get_last_lr(), on_step=True, on_epoch=True, prog_bar=True, logger=True)
        self.log("precision", precision, on_step=True, on_epoch=True, prog_bar=True, logger=True)
        self.log("recall", recall, on_step=True, on_epoch=True, prog_bar=True, logger=True)
        self.log("f1", f1, on_step=True, on_epoch=True, prog_bar=True, logger=True)

        return x_pred
    
    def test_step(self, batch, batch_idx, dataloader_idx=0):
        pass
    
    def predict(self, batch, batch_idx, dataloader_idx=0):
        pass
    
    def configure_optimizers(self):
        return self.optimizer