#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import os
import pytest
import torch
import torch.multiprocessing as mp
from pathlib import Path

import colossalai
from colossalai.core import global_context as gpc
from colossalai.utils import get_dataloader
from torchvision import transforms
from torchvision.models import resnet18
from torchvision.datasets import CIFAR10
from functools import partial

BATCH_SIZE = 16
IMG_SIZE = 224

CONFIG = dict(
    fp16=dict(
        mode=None,
    ),
    zero=dict(
        level=2,
        cpu_offload=True,
        verbose=False,
    ),
    parallel=dict(
        pipeline=dict(size=1),
        tensor=dict(size=1, mode=None)
    )
)


def run_dist(rank, world_size):
    colossalai.launch(config=CONFIG,
                      rank=rank,
                      world_size=world_size,
                      host='localhost',
                      port=29940,
                      backend='nccl')

    # build model
    model = resnet18(num_classes=10)

    # build dataloader# build dataloaders
    train_dataset = CIFAR10(
        root=Path(os.environ['DATA']),
        download=True,
        transform=transforms.Compose(
            [
                transforms.Resize(size=(IMG_SIZE, IMG_SIZE)),
                transforms.ToTensor(),
                transforms.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5))
            ]
        )
    )
    train_dataloader = get_dataloader(dataset=train_dataset,
                                      shuffle=True,
                                      batch_size=BATCH_SIZE,
                                      pin_memory=True,
                                      drop_last=True)

    # build optimizer and loss
    # optimizer = build_optimizer(global_context.config.optimizer, model)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = torch.nn.CrossEntropyLoss()

    engine, train_dataloader, *args = colossalai.initialize(model=model,
                                                            optimizer=optimizer,
                                                            criterion=criterion,
                                                            train_dataloader=train_dataloader)

    # train
    model.train()
    for idx, (data, label) in enumerate(train_dataloader):
        engine.zero_grad()
        data = data.cuda()
        label = label.cuda()

        output = engine(data)
        loss = engine.criterion(output, label)

        engine.backward(loss)
        engine.step()
        break

    gpc.destroy()
    torch.cuda.empty_cache()


@pytest.mark.dist
def test_zero_level_2():
    world_size = 4
    run_func = partial(run_dist, world_size=world_size)
    mp.spawn(run_func, nprocs=world_size)


if __name__ == '__main__':
    test_zero_level_2()
