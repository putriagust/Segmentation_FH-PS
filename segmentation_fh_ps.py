# -*- coding: utf-8 -*-
"""Segmentation_FH-PS

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/18EiYms8MX79DrVZqMBubcoDmwjrYTJQq
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

# Encoder Block
class Encoder(nn.Module):
    def __init__(self):
        super(Encoder, self).__init__()

        self.conv1 = nn.Sequential(
            nn.Conv2d(3, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )
        self.conv2 = nn.Sequential(
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )
        self.conv3 = nn.Sequential(
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )
        self.conv4 = nn.Sequential(
            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )
        self.conv5 = nn.Sequential(
            nn.Conv2d(512, 1024, kernel_size=3, padding=1),
            nn.BatchNorm2d(1024),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2)
        )

    def forward(self, x):
        x1 = self.conv1(x)  # 64x64x64
        x2 = self.conv2(x1)  # 32x32x128
        x3 = self.conv3(x2)  # 16x16x256
        x4 = self.conv4(x3)  # 8x8x512
        x5 = self.conv5(x4)  # 4x4x1024
        return x1, x2, x3, x4, x5

# Dual Attention Module
class ChannelAttention(nn.Module):
    def __init__(self, in_channels):
        super(ChannelAttention, self).__init__()
        self.softmax = nn.Softmax(dim=-1)

    def forward(self, x):
        B, C, H, W = x.size()
        proj_query = x.view(B, C, -1)
        proj_key = x.view(B, -1, C)
        attention_map = torch.bmm(proj_query, proj_key)
        attention_map = self.softmax(attention_map)
        out = torch.bmm(attention_map, proj_query).view(B, C, H, W)
        return out + x

class PositionalAttention(nn.Module):
    def __init__(self, in_channels):
        super(PositionalAttention, self).__init__()
        self.softmax = nn.Softmax(dim=-1)

    def forward(self, x):
        B, C, H, W = x.size()
        proj_query = x.view(B, C, -1).permute(0, 2, 1)
        proj_key = x.view(B, C, -1)
        attention_map = torch.bmm(proj_query, proj_key)
        attention_map = self.softmax(attention_map)
        out = torch.bmm(proj_key, attention_map.permute(0, 2, 1)).view(B, C, H, W)
        return out + x

class DualAttention(nn.Module):
    def __init__(self, in_channels):
        super(DualAttention, self).__init__()
        self.channel_attention = ChannelAttention(in_channels)
        self.positional_attention = PositionalAttention(in_channels)

    def forward(self, x):
        x_ca = self.channel_attention(x)
        x_pa = self.positional_attention(x_ca)
        return x_pa

# MSFSM Block
class MSFSM(nn.Module):
    def __init__(self, in_channels):
        super(MSFSM, self).__init__()
        self.branch1 = nn.Conv2d(in_channels, in_channels, kernel_size=1)
        self.branch2 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.branch3 = nn.Conv2d(in_channels, in_channels, kernel_size=3, padding=2, dilation=2)
        self.branch4 = nn.Conv2d(in_channels, in_channels, kernel_size=3, padding=3, dilation=3)
        self.conv_fusion = nn.Conv2d(in_channels * 4, in_channels, kernel_size=1)

    def forward(self, x):
        b1 = self.branch1(x)
        b2 = self.branch2(x)
        b2 = F.interpolate(b2, size=b1.shape[2:], mode='bilinear', align_corners=True)
        b3 = self.branch3(x)
        b4 = self.branch4(x)
        fusion = torch.cat([b1, b2, b3, b4], dim=1)
        out = self.conv_fusion(fusion)
        return out

def calculate_direction_info(segmentation_map):
    B, _, H, W = segmentation_map.shape
    direction_info = torch.zeros(B, 2, H, W)

    return direction_info

# DGB Block (updated with direction information)
class DirectionalGuidanceBlock(nn.Module):
    def __init__(self, in_channels):
        super(DirectionalGuidanceBlock, self).__init__()
        self.conv = nn.Conv2d(in_channels, in_channels, kernel_size=3, padding=1)

    def forward(self, x, direction_info):
        x = F.interpolate(x, scale_factor=2, mode='bilinear', align_corners=True)
        out = self.conv(x)

        horizontal_dir = direction_info[:, 0, :, :]  # Horizontal direction Dx_a
        vertical_dir = direction_info[:, 1, :, :]    # Vertical direction Dx_b

        return out

# Decoder Block (Updated with Direction Information and DGB)
class Decoder(nn.Module):
    def __init__(self):
        super(Decoder, self).__init__()
        self.deconv5 = nn.ConvTranspose2d(1024, 512, kernel_size=2, stride=2)
        self.deconv4 = nn.ConvTranspose2d(512 + 512, 256, kernel_size=2, stride=2)
        self.deconv3 = nn.ConvTranspose2d(256 + 256, 128, kernel_size=2, stride=2)
        self.deconv2 = nn.ConvTranspose2d(128 + 128, 64, kernel_size=2, stride=2)
        self.deconv1 = nn.ConvTranspose2d(64 + 64, 3, kernel_size=2, stride=2)
        self.dgb = DirectionalGuidanceBlock(1024)  # Adding DGB block

    def forward(self, x, skips, mask):
        # Step 1: Apply Directional Information calculation to mask
        direction_info = calculate_direction_info(mask)

        # Step 2: Use Directional Guidance Block
        x = self.dgb(x, direction_info)

        # Decoder steps with upsampling and concatenation
        x = self.deconv5(x)
        x = F.interpolate(x, size=skips[3].shape[2:], mode='bilinear', align_corners=True)
        x = torch.cat([x, skips[3]], dim=1)

        x = self.deconv4(x)
        x = F.interpolate(x, size=skips[2].shape[2:], mode='bilinear', align_corners=True)
        x = torch.cat([x, skips[2]], dim=1)

        x = self.deconv3(x)
        x = F.interpolate(x, size=skips[1].shape[2:], mode='bilinear', align_corners=True)
        x = torch.cat([x, skips[1]], dim=1)

        x = self.deconv2(x)
        x = F.interpolate(x, size=skips[0].shape[2:], mode='bilinear', align_corners=True)
        x = torch.cat([x, skips[0]], dim=1)

        x = self.deconv1(x)
        return x

# Mask Decoder for segmentation mask
class MaskDecoder(nn.Module):
    def __init__(self):
        super(MaskDecoder, self).__init__()
        self.deconv5 = nn.ConvTranspose2d(1024, 512, kernel_size=2, stride=2)
        self.deconv4 = nn.ConvTranspose2d(512, 256, kernel_size=2, stride=2)
        self.deconv3 = nn.ConvTranspose2d(256, 128, kernel_size=2, stride=2)
        self.deconv2 = nn.ConvTranspose2d(128, 64, kernel_size=2, stride=2)
        self.deconv1 = nn.ConvTranspose2d(64, 3, kernel_size=2, stride=2)

    def forward(self, x):
        x = self.deconv5(x)
        x = self.deconv4(x)
        x = self.deconv3(x)
        x = self.deconv2(x)
        x = self.deconv1(x)
        return x

# Complete Model
class CompleteModel(nn.Module):
    def __init__(self):
        super(CompleteModel, self).__init__()
        self.encoder = Encoder()
        self.dual_attention = DualAttention(1024)
        self.msfsm = MSFSM(1024)
        self.dgb = DirectionalGuidanceBlock(1024)
        self.mask_decoder = MaskDecoder()
        self.decoder = Decoder()

    def forward(self, x):
        skips = self.encoder(x)
        x = skips[-1]

        x = self.dual_attention(x)
        x = self.msfsm(x)

        mask = self.mask_decoder(x)

        output = self.decoder(x, skips[:-1], mask)

        return mask

model = CompleteModel()