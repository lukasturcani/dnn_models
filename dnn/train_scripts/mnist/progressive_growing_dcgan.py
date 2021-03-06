import logging
import argparse
import os
from os.path import join
import shutil
import torch
from torch import optim, nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
from torchvision.utils import save_image

from dnn.models.gan.growing_dcgan import GrowingGan

logger = logging.getLogger(__name__)


def train(args,
          generator,
          discriminator,
          g_optimizer,
          d_optimizer,
          train_loader,
          epoch,
          d_steps,
          fade_alpha):

    generator.train()
    discriminator.train()
    criterion = nn.BCEWithLogitsLoss()

    d_steps_done = 0
    for batch_id, (real_images, _) in enumerate(train_loader):
        real_images = (real_images - 0.5) / 0.5
        batch_size = real_images.size()[0]

        # Get real images.
        real_images = real_images.to('cuda')

        # Create fake images.
        noise = torch.randn(
            batch_size, args.g_channels[0], 1, 1, device='cuda'
        )
        fake_images = generator(noise)

        ###############################################################
        # Train the discriminator.
        ###############################################################

        d_optimizer.zero_grad()

        real_logits = discriminator(real_images)
        fake_logits = discriminator(fake_images)

        real_target = torch.ones(batch_size, device='cuda')
        real_target -= args.label_smoothing
        real_target = real_target.view_as(real_logits)
        d_real_loss = criterion(real_logits, real_target)

        fake_target = torch.zeros(batch_size, device='cuda')
        fake_target = fake_target.view_as(fake_logits)
        d_fake_loss = criterion(fake_logits, fake_target)

        d_loss = d_real_loss + d_fake_loss

        d_loss.backward()
        d_optimizer.step()

        d_steps_done += 1
        if d_steps_done < d_steps:
            continue
        d_steps_done = 0

        ###############################################################
        # Train the generator.
        ###############################################################

        g_optimizer.zero_grad()
        noise = torch.randn(
            batch_size, args.g_channels[0], 1, 1, device='cuda'
        )

        fake_images = generator(noise)
        fake_logits = discriminator(fake_images)

        fake_target = torch.ones(batch_size, device='cuda')
        fake_target = fake_target.view_as(fake_logits)
        g_loss = criterion(fake_logits, fake_target)

        g_loss.backward()
        g_optimizer.step()

        if batch_id % args.log_interval == 0:
            msg = (
                'Train Epoch: {} [{}/{} ({:.0f}%)]\t'
                'Discriminator Loss: {:.6f}\t'
                'Generator Loss: {:.6f}'
            )
            msg = msg.format(
                epoch,
                batch_id * len(real_images),
                len(train_loader.dataset),
                100. * batch_id / len(train_loader),
                d_loss.item(),
                g_loss.item()
            )
            logger.info(msg)


def test(args, generator, discriminator, test_loader, epoch):
    generator.eval()
    discriminator.eval()
    correct = fake_correct = real_correct = 0

    with torch.no_grad():
        for real_images, _ in test_loader:
            batch_real_correct = batch_fake_correct = 0
            batch_size = real_images.size()[0]

            real_images = real_images.to('cuda')

            noise = torch.randn(
                batch_size,
                args.g_channels[0],
                1,
                1,
                device='cuda'
            )

            fake_images = generator(noise)
            real_logits = discriminator(real_images)
            real_predictions = torch.sigmoid(real_logits).round()
            real_target = torch.ones(batch_size, device='cuda')
            real_target = real_target.view_as(real_predictions)
            batch_real_correct = real_predictions.eq(real_target).sum()
            real_correct += batch_real_correct.item()

            fake_logits = discriminator(fake_images)
            fake_predictions = torch.sigmoid(fake_logits).round()
            fake_target = torch.zeros(batch_size, device='cuda')
            fake_target = fake_target.view_as(fake_predictions)
            batch_fake_correct = fake_predictions.eq(fake_target).sum()
            fake_correct += batch_fake_correct.item()

    correct = real_correct + fake_correct

    msg = (
        'Test set: Accuracy: {}/{} ({:.0f}%)'
        '\tFake correct: {}\tReal correct: {}\n'
    )
    msg = msg.format(
        correct,
        2*len(test_loader.dataset),
        100. * correct / (2*len(test_loader.dataset)),
        fake_correct,
        real_correct
    )
    logger.info(msg)

    noise = torch.randn(
        20, args.g_channels[0], 1, 1, device='cuda'
    )
    g_images = generator(noise)
    save_image(
        tensor=g_images,
        filename=join(args.img_dir, f'epoch_{epoch}_generated.png'),
        normalize=True,
        scale_each=True,
        nrow=10
    )


def main():

    ###################################################################
    # Define command line parameters.
    ###################################################################

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--seed',
        default=42,
        type=int
    )
    parser.add_argument(
        '--train_batch_size',
        default=100,
        type=int
    )
    parser.add_argument(
        '--test_batch_size',
        default=1000,
        type=int
    )
    parser.add_argument(
        '--learning_rate',
        default=0.0002,
        type=float
    )
    parser.add_argument(
        '--d_channels',
        default=[1, 64, 128, 256, 512, 1024],
        type=int,
        nargs='+'
    )
    parser.add_argument(
        '--d_kernel_sizes',
        default=[1, 4, 4, 4, 4],
        type=int,
        nargs='+'
    )
    parser.add_argument(
        '--d_strides',
        default=[1, 2, 2, 2, 2],
        type=int,
        nargs='+'
    )
    parser.add_argument(
        '--d_paddings',
        default=[0, 1, 1, 1, 1],
        type=int,
        nargs='+'
    )
    parser.add_argument(
        '--d_final_kernel_size',
        default=4,
        type=int
    )
    parser.add_argument(
        '--g_channels',
        default=[100, 64*8, 64*4, 64*2, 64, 32, 1],
        type=int,
        nargs='+'
    )
    parser.add_argument(
        '--g_kernel_sizes',
        default=[4, 4, 4, 4, 4],
        type=int,
        nargs='+'
    )
    parser.add_argument(
        '--g_strides',
        default=[1, 2, 2, 2, 2],
        type=int,
        nargs='+'
    )
    parser.add_argument(
        '--g_paddings',
        default=[0, 1, 1, 1, 1],
        type=int,
        nargs='+'
    )
    parser.add_argument(
        '--lrelu_alpha',
        default=0.2,
        type=float
    )
    parser.add_argument(
        '--label_smoothing',
        default=0.3,
        type=float
    )
    parser.add_argument(
        '--logging_level',
        default=logging.DEBUG,
        type=int
    )
    parser.add_argument(
        '--log_interval',
        default=50,
        type=int
    )
    parser.add_argument(
        '--database_root',
        default='/home/lukas/databases'
    )
    parser.add_argument(
        '--img_dir',
        default='generated_images'
    )
    args = parser.parse_args()

    ###################################################################
    # Set up the output directory.
    ###################################################################

    if os.path.exists(args.img_dir):
        shutil.rmtree(args.img_dir)
    os.mkdir(args.img_dir)

    ###################################################################
    # Set up logging.
    ###################################################################

    logging_fmt = '%(asctime)s - %(levelname)s - %(module)s - %(msg)s'
    date_fmt = '%d-%m-%Y %H:%M:%S'
    logging.basicConfig(
        level=args.logging_level,
        format=logging_fmt,
        datefmt=date_fmt
    )

    ###################################################################
    # Set random seed.
    ###################################################################

    torch.manual_seed(args.seed)

    ###################################################################
    # Build the network.
    ###################################################################

    gan = GrowingGan(args=args)

    ###################################################################
    # Define network parameters.
    ###################################################################

    epoch_params = [
        (4, 1.0, 1),

        (8, 0.5, 1),
        (8, 1.0, 1),

        (16, 0.33, 1),
        (16, 0.66, 1),
        (16, 1.00, 1),
        (16, 1.00, 1),

        (32, 0.2, 1),
        (32, 0.4, 1),
        (32, 0.6, 1),
        (32, 0.8, 1),
        (32, 1.0, 1),
        (32, 1.0, 1),

        (64, 0.2, 1),
        (64, 0.4, 1),
        (64, 0.6, 1),
        (64, 0.8, 1),
        (64, 1.0, 1),
        (64, 1.0, 1),
        (64, 1.0, 1),
        (64, 1.0, 1),
        (64, 1.0, 1),
        (64, 1.0, 1),
        (64, 1.0, 1),
        (64, 1.0, 1)
    ]

    ###################################################################
    # Train.
    ###################################################################

    previous_size = None
    for epoch, e_params in enumerate(epoch_params, 1):
        img_size, fade_alpha, d_steps = e_params

        if img_size != previous_size:
            previous_size = img_size
            gan.grow()
            gan.discriminator.to('cuda')
            gan.generator.to('cuda')
            logging.debug(gan.generator)
            logging.debug(gan.discriminator)

            transform = transforms.Compose([
                transforms.Resize(img_size),
                transforms.ToTensor(),
                lambda image: (image - 0.5) * 2
            ])

            train_mnist = datasets.MNIST(
                root=args.database_root,
                train=True,
                download=True,
                transform=transform
            )
            train_loader = DataLoader(
                dataset=train_mnist,
                batch_size=args.train_batch_size,
                shuffle=True,
                num_workers=1,
                pin_memory=True
            )

            test_mnist = datasets.MNIST(
                root=args.database_root,
                train=False,
                download=True,
                transform=transform
            )
            test_loader = DataLoader(
                dataset=test_mnist,
                batch_size=args.test_batch_size,
                shuffle=True,
                num_workers=1,
                pin_memory=True
            )

            save_image(
                tensor=next(iter(test_loader))[0][:20],
                filename=join(args.img_dir, f'epoch_{epoch}_real.png'),
                normalize=True,
                scale_each=True,
                nrow=10
            )

        g_optimizer = optim.Adam(
            params=gan.generator.parameters(),
            lr=args.learning_rate,
            betas=(0.5, 0.999)
        )
        d_optimizer = optim.Adam(
            params=gan.discriminator.parameters(),
            lr=args.learning_rate,
            betas=(0.5, 0.999)
        )

        train(
            args=args,
            generator=gan.generator,
            discriminator=gan.discriminator,
            g_optimizer=g_optimizer,
            d_optimizer=d_optimizer,
            train_loader=train_loader,
            epoch=epoch,
            d_steps=d_steps,
            fade_alpha=fade_alpha
        )
        test(
            args=args,
            generator=gan.generator,
            discriminator=gan.discriminator,
            test_loader=test_loader,
            epoch=epoch
        )


if __name__ == '__main__':
    main()
