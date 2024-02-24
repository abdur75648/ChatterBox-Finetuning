import glob
import json
import os
import random
import copy

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from transformers import CLIPImageProcessor
import torchvision

from .conversation import get_default_conv_template
from .utils import (
    DEFAULT_IM_END_TOKEN,
    DEFAULT_IM_START_TOKEN,
    DEFAULT_IMAGE_PATCH_TOKEN,
    DEFAULT_IMAGE_TOKEN,
)
import re

import utils.transforms as T
from .box_ops import box_xyxy_to_cxcywh, box_xywh_to_cxcywh
from PIL import Image
import random

DEFAULT_REGION_TOKEN = "<region>"

img_size = 512

class RefCOCOGroundingDataset(torch.utils.data.Dataset):
    pixel_mean = torch.Tensor([123.675, 116.28, 103.53]).view(-1, 1, 1)
    pixel_std = torch.Tensor([58.395, 57.12, 57.375]).view(-1, 1, 1)
    img_size = img_size
    region_size = 224

    def __init__(
            self,
            base_root,
            tokenizer,
            vision_tower,
            anno_path,
            samples_per_epoch=500 * 8 * 2 * 10,
            precision: str = "fp32",
            image_size: int = 224,
            num_classes_per_sample: int = 3,
            query_bbox_rate: float = 0.5,  # note to use this args or not ?
    ):
        self.samples_per_epoch = samples_per_epoch
        self.num_classes_per_sample = num_classes_per_sample
        self.query_bbox_rate = query_bbox_rate

        self.base_root = base_root
        # self.image_size = image_size
        self.tokenizer = tokenizer
        self.precision = precision
        # self.transform = dino_transform  # transforms for dino detection
        self.clip_image_processor = CLIPImageProcessor.from_pretrained(vision_tower)

        self.data_path = os.path.join(base_root)
        with open(os.path.join(anno_path, 'CB-refcoco-GND.json')) as f:
            jack_json = json.load(f)
        self.jack_json = jack_json['data']

    def __len__(self):
        return len(self.jack_json)

    def transform(self, x):
        trans = T.Compose([
            T.RandomResize([(self.img_size, self.img_size)])  # change to Resize?
        ])

        return trans(x, target=None)

    def preprocess(self, x: torch.Tensor) -> torch.Tensor:  # resize instead of padding

        x = x.float()
        x = torchvision.transforms.functional.normalize(x, mean=[123.675, 116.28, 103.53], std=[58.395, 57.12, 57.375])

        return x

    def postprocess_bbox(self, bboxes_raw, ratios):
        h, w = self.img_size, self.img_size  # 图像的size变换 -> box的size变换
        boxes_gt = []
        for box in bboxes_raw:
            if len(box) == 0:  # this conversation has no bbox
                boxes_gt.append([])
                continue

            if isinstance(box, list):
                box = torch.tensor(box)

            ratio_width, ratio_height = ratios
            scaled_boxes = box * torch.as_tensor([ratio_width, ratio_height, ratio_width, ratio_height])

            scaled_boxes = box_xywh_to_cxcywh(scaled_boxes)
            scaled_boxes = scaled_boxes / torch.tensor([w, h, w, h], dtype=torch.float32)
            boxes_gt.append(scaled_boxes)
        return boxes_gt

    def strbbox2bbox(self, bboxes_str=None):
        if len(bboxes_str) == 0 or ";" in bboxes_str[0] or 'x1' in bboxes_str[0] or '?' in bboxes_str[0] or \
                '[0,0,0,0]' in bboxes_str[0] or '[]' in bboxes_str[0] or 'white and multi-storied and garage' in \
                bboxes_str[0] \
                or 'lap:[220, 151, 305]' in bboxes_str[0] or 'yellow and blue [equipment]' in bboxes_str[0]:
            return []
        # print('bboxes_str[0]  >>> ', bboxes_str)
        bboxes_split_str = bboxes_str[0].split(']')[:-1]
        bboxes = []
        for bbox_split_str in bboxes_split_str:
            sta = bbox_split_str.find('[')
            bbox = list(eval(bbox_split_str[sta + 1:]))

            bboxes.append(bbox)
            if len(bbox) == 0:
                print(bboxes_str)
                assert False

        return bboxes

    def __getitem__(self, idx):

        while True:
            idx = random.randint(0, len(self.jack_json) - 1)
            image_path = os.path.join(self.data_path, self.jack_json[idx]['image'])
            img = cv2.imread(image_path)
            images_ori = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            ori_size = images_ori.shape[:2]

            # preprocess images for clip
            images_clip = self.clip_image_processor.preprocess(images_ori, return_tensors="pt")[
                "pixel_values"
            ][0]
            # print('images_clip  >>> ', images_clip.shape)
            image_token_len = (images_clip.shape[1] // 14) * (
                    images_clip.shape[2] // 14
            )  # FIXME: 14 is hardcoded patch size

            images, _, ratios = self.transform(Image.fromarray(images_ori))  # preprocess images for dino, check this
            # resize = images.shape[:2]

            label = [self.jack_json[idx]["category_id"]]

            source = self.jack_json[idx]["conversation"]

            conv = get_default_conv_template(
                "vicuna"
            ).copy()  # conversation_lib.default_conversation.copy()
            roles = {"human": conv.roles[0], "gpt": conv.roles[1]}

            conversations = []
            bboxes_human = []
            bboxes_gpt = []

            if roles[source[0]["from"]] != conv.roles[0]:
                # Skip the first one if it is not from human
                source = source[1:]
            conv.messages = []

            for j, sentence in enumerate(source):  # note here: the model_max_length only contains about 6-7 VQAs
                role = roles[sentence["from"]]
                assert role == conv.roles[j % 2], f"{j}"

                if j % 2 == 0:
                    # 'the cup is on the desk. <cup:[238, 249, 298, 511], red and orange desk:[241, 289, 300, 390]>'
                    # extract the bboxes string: <cup:[238, 249, 298, 511], red and orange desk:[241, 289, 300, 390]>
                    bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                    # extract the bboxes : [[238, 249, 298, 511], [241, 289, 300, 390]]
                    bboxes = self.strbbox2bbox(bboxes_str)
                    # delete the bboxes string: 'the cup is on the desk.'
                    if "<" in sentence['value']:
                        sentence['value'] = sentence['value'][:sentence['value'].find('<')]

                    sentence['value'] = sentence['value'] + '[VG]'

                    bboxes_human.append([])

                    if j == 0:
                        sentence["value"] = '<image>\n' + ' ' + sentence["value"]  # put <image> in the most front

                elif j % 2 == 1:

                    if len(bboxes_human) > 0:
                        bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                        gt_bboxes = self.strbbox2bbox(bboxes_str)
                        if len(gt_bboxes) > 0:
                            bboxes_gpt.append(gt_bboxes)

                    if '<' in sentence['value']:
                        sentence['value'] = sentence['value'][:sentence['value'].find('<')]

                    if sum([len(bboxes) for bboxes in bboxes_gpt]) > 0 or len(source) == j + 1:
                        sentence["value"] = sentence["value"]  # + ' [VG] '

                conv.append_message(role, sentence["value"])

                if len(bboxes_human) > 0 and j % 2 == 1:
                    break

            conversations.append(conv.get_prompt())

            questions = conversations
            sampled_classes = conversations

            # replace <image> token
            # region_token_len = 256
            for i in range(len(conversations)):
                replace_token = DEFAULT_IMAGE_PATCH_TOKEN * image_token_len
                replace_token = (
                        DEFAULT_IM_START_TOKEN + replace_token + DEFAULT_IM_END_TOKEN
                )
                conversations[i] = conversations[i].replace(
                    DEFAULT_IMAGE_TOKEN, replace_token
                )

            images = self.preprocess(torch.from_numpy(np.array(images)).permute(2, 0, 1).contiguous())

            #### postprocess bbox
            bboxes_gpt = self.postprocess_bbox(bboxes_gpt, ratios)  # for DINO prediction

            # regions = self.extract_regions(bboxes_human, torch.from_numpy(images_ori))  # cast to llm together with image
            if conversations[0].count("<im_start>") == 1 and conversations[0].count("[VG]") == 1:
                # print('len of bboxes > 0  ... ', bboxes_human)
                bbox = bboxes_human[0]
                break

        return (
            images,
            images_clip,
            conversations,
            bboxes_gpt,
            label,
        )


class COCOGroundingDataset(torch.utils.data.Dataset):
    pixel_mean = torch.Tensor([123.675, 116.28, 103.53]).view(-1, 1, 1)
    pixel_std = torch.Tensor([58.395, 57.12, 57.375]).view(-1, 1, 1)
    img_size = img_size
    region_size = 224

    def __init__(
            self,
            base_root,
            tokenizer,
            vision_tower,
            anno_path,
            samples_per_epoch=500 * 8 * 2 * 10,
            precision: str = "fp32",
            image_size: int = 224,
            num_classes_per_sample: int = 3,
            query_bbox_rate: float = 0.5,  # note to use this args or not ?
    ):
        self.samples_per_epoch = samples_per_epoch
        self.num_classes_per_sample = num_classes_per_sample
        self.query_bbox_rate = query_bbox_rate

        self.base_root = base_root
        self.tokenizer = tokenizer
        self.precision = precision
        self.clip_image_processor = CLIPImageProcessor.from_pretrained(vision_tower)
        self.data_path = os.path.join(base_root)
        with open(os.path.join(anno_path, 'CB-coco-GND.json')) as f:
            jack_json = json.load(f)
        self.jack_json = jack_json['data']

    def __len__(self):
        return len(self.jack_json)

    def transform(self, x):
        trans = T.Compose([
            T.RandomResize([(self.img_size, self.img_size)])  # change to Resize?
        ])

        return trans(x, target=None)

    def preprocess(self, x: torch.Tensor) -> torch.Tensor:  # resize instead of padding

        x = x.float()
        x = torchvision.transforms.functional.normalize(x, mean=[123.675, 116.28, 103.53], std=[58.395, 57.12, 57.375])

        return x

    def postprocess_bbox(self, bboxes_raw, ratios):
        h, w = self.img_size, self.img_size  # 图像的size变换 -> box的size变换
        boxes_gt = []
        for box in bboxes_raw:
            if len(box) == 0:  # this conversation has no bbox
                boxes_gt.append([])
                continue

            if isinstance(box, list):
                box = torch.tensor(box)

            ratio_width, ratio_height = ratios
            scaled_boxes = box * torch.as_tensor([ratio_width, ratio_height, ratio_width, ratio_height])

            scaled_boxes = box_xyxy_to_cxcywh(scaled_boxes)
            scaled_boxes = scaled_boxes / torch.tensor([w, h, w, h], dtype=torch.float32)
            boxes_gt.append(scaled_boxes)
        return boxes_gt

    def strbbox2bbox(self, bboxes_str=None):
        if len(bboxes_str) == 0 or ";" in bboxes_str[0] or 'x1' in bboxes_str[0] or '?' in bboxes_str[0] or \
                '[0,0,0,0]' in bboxes_str[0] or '[]' in bboxes_str[0] or 'white and multi-storied and garage' in \
                bboxes_str[0] \
                or 'lap:[220, 151, 305]' in bboxes_str[0] or 'yellow and blue [equipment]' in bboxes_str[0]:
            return []
        bboxes_split_str = bboxes_str[0].split(']')[:-1]
        bboxes = []
        for bbox_split_str in bboxes_split_str:
            sta = bbox_split_str.find('[')
            bbox = list(eval(bbox_split_str[sta + 1:]))

            bboxes.append(bbox)
            if len(bbox) == 0:
                print(bboxes_str)
                assert False

        return bboxes

    def __getitem__(self, idx):

        while True:
            idx = random.randint(0, len(self.jack_json) - 1)
            image_path = os.path.join(self.data_path, self.jack_json[idx]['image'])
            img = cv2.imread(image_path)
            images_ori = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            ori_size = images_ori.shape[:2]

            # preprocess images for clip
            images_clip = self.clip_image_processor.preprocess(images_ori, return_tensors="pt")[
                "pixel_values"
            ][0]
            # print('images_clip  >>> ', images_clip.shape)
            image_token_len = (images_clip.shape[1] // 14) * (
                    images_clip.shape[2] // 14
            )  # FIXME: 14 is hardcoded patch size

            images, _, ratios = self.transform(Image.fromarray(images_ori))  # preprocess images for dino, check this
            # resize = images.shape[:2]

            label = [self.jack_json[idx]["category_id"]]

            source = self.jack_json[idx]["conversation"]

            conv = get_default_conv_template(
                "vicuna"
            ).copy()  # conversation_lib.default_conversation.copy()
            roles = {"human": conv.roles[0], "gpt": conv.roles[1]}

            conversations = []
            bboxes_human = []
            bboxes_gpt = []

            if roles[source[0]["from"]] != conv.roles[0]:
                # Skip the first one if it is not from human
                source = source[1:]
            conv.messages = []

            for j, sentence in enumerate(source):  # note here: the model_max_length only contains about 6-7 VQAs
                role = roles[sentence["from"]]
                assert role == conv.roles[j % 2], f"{j}"

                if j % 2 == 0:
                    # 'the cup is on the desk. <cup:[238, 249, 298, 511], red and orange desk:[241, 289, 300, 390]>'
                    # extract the bboxes string: <cup:[238, 249, 298, 511], red and orange desk:[241, 289, 300, 390]>
                    bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                    # extract the bboxes : [[238, 249, 298, 511], [241, 289, 300, 390]]
                    bboxes = self.strbbox2bbox(bboxes_str)
                    # delete the bboxes string: 'the cup is on the desk.'
                    if "<" in sentence['value']:
                        sentence['value'] = sentence['value'][:sentence['value'].find('<')]

                    sentence['value'] = sentence['value'] + '[VG]'

                    bboxes_human.append([])

                    if j == 0:
                        sentence["value"] = '<image>\n' + ' ' + sentence["value"]  # put <image> in the most front

                elif j % 2 == 1:

                    if len(bboxes_human) > 0:
                        bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                        gt_bboxes = self.strbbox2bbox(bboxes_str)
                        if len(gt_bboxes) > 0:
                            bboxes_gpt.append(gt_bboxes)

                    if '<' in sentence['value']:
                        sentence['value'] = sentence['value'][:sentence['value'].find('<')]

                    if sum([len(bboxes) for bboxes in bboxes_gpt]) > 0 or len(source) == j + 1:
                        sentence["value"] = sentence["value"]  # + ' [VG] '

                conv.append_message(role, sentence["value"])

                if len(bboxes_human) > 0 and j % 2 == 1:
                    break

            conversations.append(conv.get_prompt())

            questions = conversations
            sampled_classes = conversations

            # replace <image> token
            # region_token_len = 256
            for i in range(len(conversations)):
                replace_token = DEFAULT_IMAGE_PATCH_TOKEN * image_token_len
                replace_token = (
                        DEFAULT_IM_START_TOKEN + replace_token + DEFAULT_IM_END_TOKEN
                )
                conversations[i] = conversations[i].replace(
                    DEFAULT_IMAGE_TOKEN, replace_token
                )

            images = self.preprocess(torch.from_numpy(np.array(images)).permute(2, 0, 1).contiguous())

            #### postprocess bbox
            bboxes_gpt = self.postprocess_bbox(bboxes_gpt, ratios)  # for DINO prediction

            # regions = self.extract_regions(bboxes_human, torch.from_numpy(images_ori))  # cast to llm together with image
            if conversations[0].count("<im_start>") == 1 and conversations[0].count("[VG]") == 1:
                # print('len of bboxes > 0  ... ', bboxes_human)
                bbox = bboxes_human[0]
                break

        return (
            images,
            images_clip,
            conversations,
            bboxes_gpt,
            label,
        )
        
# class JackGroundingDataset(torch.utils.data.Dataset):
class MyGroundingDataset(torch.utils.data.Dataset):
    pixel_mean = torch.Tensor([123.675, 116.28, 103.53]).view(-1, 1, 1)
    pixel_std = torch.Tensor([58.395, 57.12, 57.375]).view(-1, 1, 1)
    img_size = img_size
    region_size = 224

    def __init__(
            self,
            base_root,
            tokenizer,
            vision_tower,
            anno_path,
            precision: str = "fp32",
            image_size: int = 224,
            num_classes_per_sample: int = 3,
            query_bbox_rate: float = 0.5,  # note to use this args or not ?
    ):
        self.num_classes_per_sample = num_classes_per_sample
        self.query_bbox_rate = query_bbox_rate

        self.base_root = base_root
        # self.image_size = image_size
        self.tokenizer = tokenizer
        self.precision = precision
        # self.transform = dino_transform  # transforms for dino detection
        self.clip_image_processor = CLIPImageProcessor.from_pretrained(vision_tower)
        self.data_path = os.path.join(base_root)
        with open(os.path.join(anno_path, 'apollo_16k_GND.json')) as f:
            jack_json = json.load(f)
        self.jack_json = jack_json['data']

        self.replace_names = ['the region', 'this region']

        self.first_q = "This is an image of a user interface. Given a task and previous action done on the app, can you please tell me the next step to complete the task"
        self.first_a = "Sure, I can provide the next action you need to take on this interface. Please provide the task details, image, and any actions you've already taken."

    def __len__(self):
        return len(self.jack_json)

    def transform(self, x):
        trans = T.Compose([
            T.RandomResize([(self.img_size, self.img_size)])  # change to Resize?
        ])

        return trans(x, target=None)

    def preprocess(self, x: torch.Tensor) -> torch.Tensor:  # resize instead of padding

        x = x.float()
        x = torchvision.transforms.functional.normalize(x, mean=[123.675, 116.28, 103.53], std=[58.395, 57.12, 57.375])

        return x

    def postprocess_bbox(self, bboxes_raw, ratios):

        h, w = self.img_size, self.img_size  # 图像的size变换 -> box的size变换
        boxes_gt = []
        for box in bboxes_raw:
            if len(box) == 0:  # this conversation has no bbox
                boxes_gt.append([])
                continue

            if isinstance(box, list):
                box = torch.tensor(box)

            ratio_width, ratio_height = ratios
            scaled_boxes = box * torch.as_tensor([ratio_width, ratio_height, ratio_width, ratio_height])

            scaled_boxes = box_xyxy_to_cxcywh(scaled_boxes)
            scaled_boxes = scaled_boxes / torch.tensor([w, h, w, h], dtype=torch.float32)
            boxes_gt.append(scaled_boxes)
        return boxes_gt

    def strbbox2bbox(self, bboxes_str=None):
        if len(bboxes_str) == 0 or ";" in bboxes_str[0] or 'x1' in bboxes_str[0] or '?' in bboxes_str[0] or \
                '[0,0,0,0]' in bboxes_str[0] or '[]' in bboxes_str[0] or 'white and multi-storied and garage' in \
                bboxes_str[0] \
                or 'lap:[220, 151, 305]' in bboxes_str[0] or 'yellow and blue [equipment]' in bboxes_str[0]:
            return []
        bboxes_split_str = bboxes_str[0].split(']')[:-1]
        bboxes = []
        for bbox_split_str in bboxes_split_str:
            sta = bbox_split_str.find('[')
            bbox = list(eval(bbox_split_str[sta + 1:]))

            bboxes.append(bbox)
            if len(bbox) == 0:
                print(bboxes_str)
                assert False

        return bboxes

    def __getitem__(self, idx):

        idx = random.randint(0, len(self.jack_json) - 1)
        image_path = os.path.join(self.data_path, self.jack_json[idx]['image'])
        img = cv2.imread(image_path)
        images_ori = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        ori_size = images_ori.shape[:2]

        # preprocess images for clip
        images_clip = self.clip_image_processor.preprocess(images_ori, return_tensors="pt")[
            "pixel_values"
        ][0]
        image_token_len = (images_clip.shape[1] // 14) * (
                images_clip.shape[2] // 14
        )  # FIXME: 14 is hardcoded patch size

        images, _, ratios = self.transform(Image.fromarray(images_ori))  # preprocess images for dino, check this
        # resize = images.shape[:2]

        source = copy.deepcopy(self.jack_json[idx]["conversation"])

        conv = get_default_conv_template(
            "vicuna"
        ).copy()  # conversation_lib.default_conversation.copy()
        roles = {"human": conv.roles[0], "gpt": conv.roles[1]}

        conversations = []
        # bboxes_human = []
        bboxes_gpt = []

        replace_name = -2
        # random sample convs from start_id -> note logical reasoning NOT has this
        len_conv = len(source)
        start_id = 0
        if len(source) != 2:
            raise ValueError("The length of sample conversation is not 2")

        if roles[source[0]["from"]] != conv.roles[0]:
            raise ValueError("The first role is not human")
        conv.messages = []

        # Here len(source) == 2
        # j==0 means human
        # j==1 means gpt
        for sentence in source:
            role = roles[sentence["from"]]
            if sentence["from"] == "human":
                bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                # sentence['value'] = sentence['value'][:sentence['value'].find('<')]
                if len(bboxes_str) > 0:
                    print(idx)
                    print("source = ",source)
                    raise ValueError("The human inputs cannot contain any bounding boxes")
                sentence["value"] = '<image>\n' + ' ' + sentence["value"] + '[VG]'  # put <image> in the most front
            elif sentence["from"] == "gpt":
                bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                if len(bboxes_str) !=1:
                    print(idx)
                    print(bboxes_str)
                    print(sentence["value"])
                    print("source = ",source)
                    raise ValueError("The gpt inputs should contain only one bounding box")
                gt_bboxes = self.strbbox2bbox(bboxes_str)
                
                bboxes_gpt.append(gt_bboxes[0])
                if '<' in sentence['value']:
                    sentence['value'] = sentence['value'][:sentence['value'].find('<')]
            else:
                raise ValueError("Only human and GPT source can be there")
                
        # for j, sentence in enumerate(source):  # note here: the model_max_length only contains about 6-7 VQAs
        #     role = roles[sentence["from"]]
        #     assert role == conv.roles[j % 2], f"{j}"

        #     if j % 2 == 0:
        #         # First One (From Human)
        #         bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
        #         sentence['value'] = sentence['value'][:sentence['value'].find('<')]
        #         if len(bboxes_str) > 0:
        #             print(idx)
        #             print("source = ",source)
        #             raise ValueError("The human inputs cannot contain any bounding boxes")
        #         sentence["value"] = '<image>\n' + ' ' + sentence["value"]  # put <image> in the most front

        #     elif j % 2 == 1:
        #         # Second One (From GPT)
        #         bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
        #         if len(bboxes_str) !=1:
        #             print(idx)
        #             print("source = ",source)
        #             raise ValueError("The gpt inputs should contain only one bounding box")
        #         gt_bboxes = self.strbbox2bbox(bboxes_str)
        #         bboxes_gpt.append(gt_bboxes[0])
                
        #         if '<' in sentence['value']:
        #             sentence['value'] = sentence['value'][:sentence['value'].find('<')]

            conv.append_message(role, sentence["value"])

        conversations.append(conv.get_prompt())

        # replace <image> token
        # region_token_len = 256
        for i in range(len(conversations)):
            replace_token = DEFAULT_IMAGE_PATCH_TOKEN * image_token_len
            replace_token = (
                    DEFAULT_IM_START_TOKEN + replace_token + DEFAULT_IM_END_TOKEN
            )
            conversations[i] = conversations[i].replace(
                DEFAULT_IMAGE_TOKEN, replace_token
            )

        # images = self.preprocess(torch.from_numpy(images).permute(2, 0, 1).contiguous())
        images = self.preprocess(torch.from_numpy(np.array(images)).permute(2, 0, 1).contiguous())

        #### postprocess bbox
        bboxes_gpt = self.postprocess_bbox(bboxes_gpt, ratios)  # for DINO prediction
        
        label = -1

        return (
            images, # torch.Size([3, 512, 512])
            images_clip, # torch.Size([3, 224, 224])
            conversations, # list
            bboxes_gpt, # list
            [label], # list
        )


class JackGroundingDataset(torch.utils.data.Dataset):
    pixel_mean = torch.Tensor([123.675, 116.28, 103.53]).view(-1, 1, 1)
    pixel_std = torch.Tensor([58.395, 57.12, 57.375]).view(-1, 1, 1)
    img_size = img_size
    region_size = 224

    def __init__(
            self,
            base_root,
            tokenizer,
            vision_tower,
            anno_path,
            samples_per_epoch=500 * 8 * 2 * 10,
            precision: str = "fp32",
            image_size: int = 224,
            num_classes_per_sample: int = 3,
            query_bbox_rate: float = 0.5,  # note to use this args or not ?
    ):
        self.samples_per_epoch = samples_per_epoch
        self.num_classes_per_sample = num_classes_per_sample
        self.query_bbox_rate = query_bbox_rate

        self.base_root = base_root
        # self.image_size = image_size
        self.tokenizer = tokenizer
        self.precision = precision
        # self.transform = dino_transform  # transforms for dino detection
        self.clip_image_processor = CLIPImageProcessor.from_pretrained(vision_tower)
        self.data_path = os.path.join(base_root)
        with open(os.path.join(anno_path, 'CB_GND.json')) as f:
            jack_json = json.load(f)
        self.jack_json = jack_json['data']

        self.replace_names = ['the region', 'this region']

        self.first_q = "This is an image. Can you answer the next questions about the specific regions in the image?  "
        self.first_a = "Sure, I will answer your questions.  "

    def __len__(self):
        return len(self.jack_json)

    def transform(self, x):
        trans = T.Compose([
            T.RandomResize([(self.img_size, self.img_size)])  # change to Resize?
        ])

        return trans(x, target=None)

    def preprocess(self, x: torch.Tensor) -> torch.Tensor:  # resize instead of padding

        x = x.float()
        x = torchvision.transforms.functional.normalize(x, mean=[123.675, 116.28, 103.53], std=[58.395, 57.12, 57.375])

        return x

    def postprocess_bbox(self, bboxes_raw, ratios):

        h, w = self.img_size, self.img_size  # 图像的size变换 -> box的size变换
        boxes_gt = []
        for box in bboxes_raw:
            if len(box) == 0:  # this conversation has no bbox
                boxes_gt.append([])
                continue

            if isinstance(box, list):
                box = torch.tensor(box)

            ratio_width, ratio_height = ratios
            scaled_boxes = box * torch.as_tensor([ratio_width, ratio_height, ratio_width, ratio_height])

            scaled_boxes = box_xyxy_to_cxcywh(scaled_boxes)
            scaled_boxes = scaled_boxes / torch.tensor([w, h, w, h], dtype=torch.float32)
            boxes_gt.append(scaled_boxes)
        return boxes_gt

    def strbbox2bbox(self, bboxes_str=None):
        if len(bboxes_str) == 0 or ";" in bboxes_str[0] or 'x1' in bboxes_str[0] or '?' in bboxes_str[0] or \
                '[0,0,0,0]' in bboxes_str[0] or '[]' in bboxes_str[0] or 'white and multi-storied and garage' in \
                bboxes_str[0] \
                or 'lap:[220, 151, 305]' in bboxes_str[0] or 'yellow and blue [equipment]' in bboxes_str[0]:
            return []
        bboxes_split_str = bboxes_str[0].split(']')[:-1]
        bboxes = []
        for bbox_split_str in bboxes_split_str:
            sta = bbox_split_str.find('[')
            bbox = list(eval(bbox_split_str[sta + 1:]))

            bboxes.append(bbox)
            if len(bbox) == 0:
                print(bboxes_str)
                assert False

        return bboxes

    def __getitem__(self, idx):

        # while True:
        idx = random.randint(0, len(self.jack_json) - 1)
        image_path = os.path.join(self.data_path, self.jack_json[idx]['image'])
        img = cv2.imread(image_path)
        images_ori = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        ori_size = images_ori.shape[:2]

        # preprocess images for clip
        images_clip = self.clip_image_processor.preprocess(images_ori, return_tensors="pt")[
            "pixel_values"
        ][0]
        image_token_len = (images_clip.shape[1] // 14) * (
                images_clip.shape[2] // 14
        )  # FIXME: 14 is hardcoded patch size

        images, _, ratios = self.transform(Image.fromarray(images_ori))  # preprocess images for dino, check this
        # resize = images.shape[:2]

        source = self.jack_json[idx]["conversation"]

        conv = get_default_conv_template(
            "vicuna"
        ).copy()  # conversation_lib.default_conversation.copy()
        roles = {"human": conv.roles[0], "gpt": conv.roles[1]}

        conversations = []
        bboxes_human = []
        bboxes_gpt = []

        replace_name = -2
        # random sample convs from start_id -> note logical reasoning NOT has this
        len_conv = len(source)
        start_id = 0
        if len_conv > 2:
            rand_id = random.randint(0, len_conv - 1)
            start_id = \
            random.sample([rand_id, int(len_conv // 2), int(len_conv // 4), int(len_conv // 6), int(len_conv // 8)],
                          1)[0]
            start_id = start_id // 2 * 2
            source = source[start_id:]

        if roles[source[0]["from"]] != conv.roles[0]:
            # Skip the first one if it is not from human
            source = source[1:]
        conv.messages = []

        label = -1

        for j, sentence in enumerate(source):  # note here: the model_max_length only contains about 6-7 VQAs
            role = roles[sentence["from"]]
            assert role == conv.roles[j % 2], f"{j}"

            if j % 2 == 0:

                # 'the cup is on the desk. <cup:[238, 249, 298, 511], red and orange desk:[241, 289, 300, 390]>'
                # extract the bboxes string: <cup:[238, 249, 298, 511], red and orange desk:[241, 289, 300, 390]>
                bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                sentence['value'] = sentence['value'][:sentence['value'].find('<')]

                bboxes_human.append([])

                ########################## find coco classes #########################
                sentence_next = source[j + 1]
                bboxes_str_next = re.findall(r"<(.+?)>", sentence_next["value"])
                bboxes_next = self.strbbox2bbox(bboxes_str_next)
                if len(bboxes_next) == 1:
                    ins_name = bboxes_str_next[0].split('<')[-1].split(':')[0]
                ######################################################################
                if label != -1:
                    sentence["value"] = sentence["value"] + '[VG]'

                if j == 0:
                    sentence["value"] = '<image>\n' + ' ' + sentence["value"]  # put <image> in the most front

            elif j % 2 == 1:
                # if label != -1:
                bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                gt_bboxes = self.strbbox2bbox(bboxes_str)
                if len(gt_bboxes) > 0:
                    bboxes_gpt.append(gt_bboxes)

                if '<' in sentence['value']:
                    sentence['value'] = sentence['value'][:sentence['value'].find('<')]

                if replace_name == j - 1:
                    if ins_name in sentence["value"]:
                        sentence["value"] = sentence["value"].replace(ins_name, name_re)

            conv.append_message(role, sentence["value"])

            if j==1:
                break

            # if label != -1 and j % 2 == 1:
            #     break

            conversations.append(conv.get_prompt())

            questions = conversations
            sampled_classes = conversations

            # replace <image> token
            # region_token_len = 256
            for i in range(len(conversations)):
                replace_token = DEFAULT_IMAGE_PATCH_TOKEN * image_token_len
                replace_token = (
                        DEFAULT_IM_START_TOKEN + replace_token + DEFAULT_IM_END_TOKEN
                )
                conversations[i] = conversations[i].replace(
                    DEFAULT_IMAGE_TOKEN, replace_token
                )

            # images = self.preprocess(torch.from_numpy(images).permute(2, 0, 1).contiguous())
            images = self.preprocess(torch.from_numpy(np.array(images)).permute(2, 0, 1).contiguous())

            #### postprocess bbox
            bboxes_gpt = self.postprocess_bbox(bboxes_gpt, ratios)  # for DINO prediction
            # print('JackGroundingDataset >>', bboxes_gpt)

            # if conversations[0].count("<im_start>") == 1 and conversations[0].count("[VG]") == 1 and label != -1:
            #     break

        return (
            images,
            images_clip,
            conversations,
            bboxes_gpt,
            [label],
        )


class JackLogicGroundingDataset(torch.utils.data.Dataset):
    pixel_mean = torch.Tensor([123.675, 116.28, 103.53]).view(-1, 1, 1)
    pixel_std = torch.Tensor([58.395, 57.12, 57.375]).view(-1, 1, 1)
    img_size = img_size
    region_size = 224

    def __init__(
            self,
            base_root,
            tokenizer,
            vision_tower,
            anno_path,
            samples_per_epoch=500 * 8 * 2 * 10,
            precision: str = "fp32",
            image_size: int = 224,
            num_classes_per_sample: int = 3,
            query_bbox_rate: float = 0.5,  # note to use this args or not ?
    ):
        self.samples_per_epoch = samples_per_epoch
        self.num_classes_per_sample = num_classes_per_sample
        self.query_bbox_rate = query_bbox_rate

        self.base_root = base_root
        # self.image_size = image_size
        self.tokenizer = tokenizer
        self.precision = precision
        # self.transform = dino_transform  # transforms for dino detection
        self.clip_image_processor = CLIPImageProcessor.from_pretrained(vision_tower)
        self.data_path = os.path.join(base_root)
        with open(os.path.join(anno_path, 'CB_LC.json')) as f:
            jack_json = json.load(f)
        self.jack_json = jack_json['data']

    def __len__(self):
        return len(self.jack_json)

    def transform(self, x):
        trans = T.Compose([
            T.RandomResize([(self.img_size, self.img_size)])  # change to Resize?
        ])

        return trans(x, target=None)

    def preprocess(self, x: torch.Tensor) -> torch.Tensor:  # resize instead of padding

        x = x.float()
        x = torchvision.transforms.functional.normalize(x, mean=[123.675, 116.28, 103.53], std=[58.395, 57.12, 57.375])

        return x

    def postprocess_bbox(self, bboxes_raw, ratios):

        h, w = self.img_size, self.img_size  # 图像的size变换 -> box的size变换
        boxes_gt = []
        for box in bboxes_raw:
            if len(box) == 0:  # this conversation has no bbox
                boxes_gt.append([])
                continue

            if isinstance(box, list):
                box = torch.tensor(box)

            ratio_width, ratio_height = ratios
            scaled_boxes = box * torch.as_tensor([ratio_width, ratio_height, ratio_width, ratio_height])

            scaled_boxes = box_xyxy_to_cxcywh(scaled_boxes)
            scaled_boxes = scaled_boxes / torch.tensor([w, h, w, h], dtype=torch.float32)
            boxes_gt.append(scaled_boxes)
        return boxes_gt

    def strbbox2bbox(self, bboxes_str=None):
        if len(bboxes_str) == 0:
            return []
        bboxes_split_str = bboxes_str[0].split(']')[:-1]
        bboxes = []
        for bbox_split_str in bboxes_split_str:
            sta = bbox_split_str.find('[')
            bbox = list(eval(bbox_split_str[sta + 1:]))

            bboxes.append(bbox)
            if len(bbox) == 0:
                print(bboxes_str)
                assert False

        return bboxes

    def __getitem__(self, idx):

        while True:
            idx = random.randint(0, len(self.jack_json) - 1)
            image_path = os.path.join(self.data_path, self.jack_json[idx]['image'])
            img = cv2.imread(image_path)
            images_ori = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            ori_size = images_ori.shape[:2]

            # preprocess images for clip
            images_clip = self.clip_image_processor.preprocess(images_ori, return_tensors="pt")[
                "pixel_values"
            ][0]
            # print('images_clip  >>> ', images_clip.shape)
            image_token_len = (images_clip.shape[1] // 14) * (
                    images_clip.shape[2] // 14
            )  # FIXME: 14 is hardcoded patch size

            images, _, ratios = self.transform(Image.fromarray(images_ori))  # preprocess images for dino, check this
            # resize = images.shape[:2]

            source = self.jack_json[idx]["conversation"]

            conv = get_default_conv_template(
                "vicuna"
            ).copy()  # conversation_lib.default_conversation.copy()
            roles = {"human": conv.roles[0], "gpt": conv.roles[1]}

            conversations = []
            bboxes_human = []
            bboxes_gpt = []

            if roles[source[0]["from"]] != conv.roles[0]:
                # Skip the first one if it is not from human
                source = source[1:]
            conv.messages = []

            label = -1

            for j, sentence in enumerate(source):  # note here: the model_max_length only contains about 6-7 VQAs
                role = roles[sentence["from"]]
                assert role == conv.roles[j % 2], f"{j}"

                if j % 2 == 0:
                    # 'the cup is on the desk. <cup:[238, 249, 298, 511], red and orange desk:[241, 289, 300, 390]>'
                    # extract the bboxes string: <cup:[238, 249, 298, 511], red and orange desk:[241, 289, 300, 390]>
                    bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                    # extract the bboxes : [[238, 249, 298, 511], [241, 289, 300, 390]]
                    bboxes = self.strbbox2bbox(bboxes_str)
                    # delete the bboxes string: 'the cup is on the desk.'
                    if "<" in sentence['value']:
                        sentence['value'] = sentence['value'][:sentence['value'].find('<')]

                    sentence['value'] = sentence['value'].replace('[it]', 'it')

                    ########################## find coco classes #########################
                    sentence_next = source[j + 1]
                    bboxes_str_next = re.findall(r"<(.+?)>", sentence_next["value"])
                    bboxes_next = self.strbbox2bbox(bboxes_str_next)
                    # print('bboxes_str_next   >>>', bboxes_str_next)
                    if len(bboxes_next) == 1:
                        ins_name = bboxes_str_next[0].split('<')[-1].split(':')[0]

                    ######################################################################
                    if label != -1:
                        sentence["value"] = sentence["value"] + '[VG]'

                    bboxes_human.append([])

                    if j == 0:
                        sentence["value"] = '<image>\n' + ' ' + sentence["value"]  # put <image> in the most front

                elif j % 2 == 1:
                    if label != -1:
                        bboxes_str = re.findall(r"<(.+?)>", sentence["value"])
                        gt_bboxes = self.strbbox2bbox(bboxes_str)
                        if len(gt_bboxes) == 1:
                            bboxes_gpt.append(gt_bboxes)

                    if '<' in sentence['value']:
                        sentence['value'] = sentence['value'][:sentence['value'].find('<')]

                conv.append_message(role, sentence["value"])

                if label != -1 and j % 2 == 1:
                    break

            conversations.append(conv.get_prompt())

            questions = conversations
            sampled_classes = conversations

            # replace <image> token
            # region_token_len = 256
            for i in range(len(conversations)):
                replace_token = DEFAULT_IMAGE_PATCH_TOKEN * image_token_len
                replace_token = (
                        DEFAULT_IM_START_TOKEN + replace_token + DEFAULT_IM_END_TOKEN
                )
                conversations[i] = conversations[i].replace(
                    DEFAULT_IMAGE_TOKEN, replace_token
                )

            # images = self.preprocess(torch.from_numpy(images).permute(2, 0, 1).contiguous())
            images = self.preprocess(torch.from_numpy(np.array(images)).permute(2, 0, 1).contiguous())

            #### postprocess bbox
            bboxes_gpt = self.postprocess_bbox(bboxes_gpt, ratios)  # for DINO prediction

            # regions = self.extract_regions(bboxes_human, torch.from_numpy(images_ori))  # cast to llm together with image
            if conversations[0].count("<im_start>") == 1 and conversations[0].count("[VG]") == 1 and label != -1:
                break

        return (
            images,
            images_clip,
            conversations,
            bboxes_gpt,
            [label],
        )


def collate_fn(batch, tokenizer=None):
    images_list = []
    images_clip_list = []
    conversation_list = []
    bboxes_gt_list = []
    label_list = []
    offset_list = [0]
    cnt = 0
    for (
            images,
            images_clip,
            conversations,
            bbox,
            label,
    ) in batch:
        images_list.append(images)
        images_clip_list.append(images_clip)
        conversation_list.extend(conversations)
        label_list.append(label)
        bboxes_gt_list.append(bbox)
        cnt += len(conversations)
        offset_list.append(cnt)

    tokenize_data = tokenizer(
        conversation_list,
        return_tensors="pt",
        padding="longest",
        max_length=tokenizer.model_max_length,
        truncation=True,
    )

    input_ids = tokenize_data.input_ids
    attention_masks = tokenize_data.attention_mask

    IGNORE_TOKEN_ID = -100
    conv = get_default_conv_template("vicuna").copy()
    targets = input_ids.clone()
    sep = conv.sep + conv.roles[1] + ": "
    for conversation, target in zip(conversation_list, targets):
        total_len = int(target.ne(tokenizer.pad_token_id).sum())

        rounds = conversation.split(conv.sep2)
        cur_len = 1
        target[:cur_len] = IGNORE_TOKEN_ID
        for i, rou in enumerate(rounds):
            if rou == "":
                break

            parts = rou.split(sep)
            assert len(parts) == 2, (len(parts), rou)
            parts[0] += sep
            round_len = len(tokenizer(rou).input_ids)
            instruction_len = len(tokenizer(parts[0]).input_ids) - 2

            target[cur_len: cur_len + instruction_len] = IGNORE_TOKEN_ID

            cur_len += round_len
        target[cur_len:] = IGNORE_TOKEN_ID

        if cur_len < tokenizer.model_max_length:
            assert cur_len == total_len

    return {
        "images": torch.stack(images_list, dim=0),
        "images_clip": torch.stack(images_clip_list, dim=0),
        "input_ids": input_ids,
        "attention_masks": attention_masks,
        "offset": torch.LongTensor(offset_list),
        "labels": targets,
        "label_list": label_list,
        "bboxes_gt_list": bboxes_gt_list,
    }


class GroundingDataset(torch.utils.data.Dataset):
    pixel_mean = torch.Tensor([123.675, 116.28, 103.53]).view(-1, 1, 1)
    pixel_std = torch.Tensor([58.395, 57.12, 57.375]).view(-1, 1, 1)
    img_size = 768


    def __init__(
            self,
            base_image_dir,
            tokenizer,
            vision_tower,
            dataset="jack||vqa",
            sample_rate=[7, 3],
            vqa_data='llava_instruct_150k'
    ):
        # dataset = "refcocoground||cocoground||jackground||jacklogicground"
        # sample_rate = [5, 8, 1, 1]

        sample_rate = np.array(sample_rate)
        self.sample_rate = sample_rate / sample_rate.sum()

        self.base_image_dir = base_image_dir
        self.tokenizer = tokenizer

        self.datasets = dataset.split("||")

        self.numSamples = 0

        self.all_datasets = []
        for dataset in self.datasets:
            if dataset == "refcocoground":
                self.all_datasets.append(
                    RefCOCOGroundingDataset(
                        base_root="../datasets/MSCOCO2014/train2014/",
                        tokenizer=tokenizer,
                        vision_tower="openai/clip-vit-large-patch14",
                        anno_path="../datasets/CB-materials/"
                    )
                )
                self.numSamples += len(self.all_datasets[-1])
            elif dataset == "cocoground":
                self.all_datasets.append(
                    COCOGroundingDataset(
                        base_root="../datasets/MSCOCO2017/train2017/",
                        tokenizer=tokenizer,
                        vision_tower="openai/clip-vit-large-patch14",
                        anno_path='../datasets/CB-materials/'
                    )
                )
                self.numSamples += len(self.all_datasets[-1])
            elif dataset == "jackground":
                self.all_datasets.append(
                    JackGroundingDataset(
                        base_root="CB-300K/",
                        tokenizer=tokenizer,
                        vision_tower="openai/clip-vit-large-patch14",
                        anno_path='CB-300K/'
                    )
                )
                self.numSamples += len(self.all_datasets[-1])
            elif dataset == "mygr":
                self.all_datasets.append(
                    MyGroundingDataset(
                        base_root="16k-Apollo-MLLM-data", # path to images in grounding_gt.json
                        tokenizer=tokenizer,
                        vision_tower=vision_tower,
                        anno_path='16k-Apollo-MLLM-data'
                    )
                )
                self.numSamples += len(self.all_datasets[-1])
            elif dataset == "jacklogicground":
                self.all_datasets.append(
                    JackLogicGroundingDataset(
                        base_root="CB-300K/",
                        tokenizer=tokenizer,
                        vision_tower="openai/clip-vit-large-patch14",
                        anno_path='CB-300K/'
                    )
                )
                self.numSamples += len(self.all_datasets[-1])
    def __len__(self):
        return self.numSamples

    def __getitem__(self, idx):
        ind = np.random.choice(list(range(len(self.all_datasets))), p=self.sample_rate)
        dataset_part = self.all_datasets[ind]

        return dataset_part[0]
