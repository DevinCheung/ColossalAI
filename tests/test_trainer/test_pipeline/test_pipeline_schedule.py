# referenced from Megatron and used to testify communication

import colossalai
import os
import os.path as osp
import pytest
import torch
import torch.multiprocessing as mp
import model

from colossalai.builder import PipelineModelInitializer
from colossalai.communication import p2p as p2p_communication
from colossalai.communication.utils import send_tensor_meta, recv_tensor_meta
from colossalai.context.parallel_mode import ParallelMode
from colossalai.core import global_context as gpc
from colossalai.initialize import launch
from colossalai.utils import print_rank_0, get_current_device, get_dataloader
from colossalai.engine.schedule import PipelineSchedule
from torchvision.datasets import CIFAR10
from torchvision import transforms
from pathlib import Path
from functools import partial


BATCH_SIZE = 32
NUM_MICRO = 8


DIR_PATH = osp.dirname(osp.realpath(__file__))
CONFIG_PATH = osp.join(DIR_PATH, './resnet_config.py')


def run_schedule(rank, world_size):
    launch(config=CONFIG_PATH,
           rank=rank,
           world_size=world_size,
           host='localhost',
           port=29934,
           backend='nccl')

    # build model
    model = PipelineModelInitializer(gpc.config.model, 1).initialize()
    print_rank_0('model is created')

    train_dataset = CIFAR10(
        root=Path(os.environ['DATA']),
        download=True,
        transform=transforms.Compose(
            [
                transforms.RandomCrop(size=32, padding=4),
                transforms.RandomHorizontalFlip(),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.4914, 0.4822, 0.4465], std=[
                    0.2023, 0.1994, 0.2010]),
            ]
        )
    )

    train_dataloader = get_dataloader(dataset=train_dataset,
                                      shuffle=True,
                                      add_sampler=True,
                                      batch_size=BATCH_SIZE,
                                      pin_memory=True,
                                      )

    # build criterion
    criterion = torch.nn.CrossEntropyLoss()

    # optimizer
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001, weight_decay=0)

    # initialize
    engine, train_dataloader, _, _ = colossalai.initialize(model, optimizer, criterion, train_dataloader)

    # build pipeline schedule
    schedule = PipelineSchedule(num_microbatches=NUM_MICRO)

    # run schedule
    data_iter = iter(train_dataloader)
    schedule.forward_backward_step(engine, data_iter)

    gpc.destroy()
    torch.cuda.empty_cache()


@pytest.mark.dist
def test_pipeline_schedule():
    world_size = 4
    run_func = partial(run_schedule, world_size=world_size)
    mp.spawn(run_func, nprocs=world_size)


if __name__ == '__main__':
    test_pipeline_schedule()
