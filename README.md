<h1>ChatterBox </h1>

## Contents

- [Install](#install)
- [Train](#train)
- [Evaluation](#evaluation)
- [Demo](#demo)

## Install

1. Clone this repository and navigate to ChatterBox folder

```bash
git https://github.com/abdur75648/ChatterBox-Finetuning.git
cd ChatterBox-Finetuning
```

2.1 Install Packages (Runpod)
```Shell
apt-get update
apt-get install zip unzip
pip install --upgrade pip
pip install -r requirements.txt
rm -rf CB-300K
mkdir CB-300K && cd CB-300K
gdown --id 1vAqozQ3En5xSEIhzCp4WnUeWztYzZGQY
gdown --id 1C0XyMyhLRzdSDbtWAiGdW1rjljop0sMe
gdown --id 16CaLpXiiudAKP40ESKUjhquzWa0OTXaF
gdown --id 1--RcXrmY0yl4OFE-sDe_vZcbanJG5tUG
unzip images.zip
unzip images2.zip
rm *.zip
cd ..
cd llava-llama-2-13b-chat-lightning-preview
bash download_model.sh
cd ..
unzip mmcv-1.4.7.zip
cd mmcv-1.4.7/
MMCV_WITH_OPS=1 pip install -e .
cd ../model/GroundingDINO/ops
python setup.py build install
wget https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha2/groundingdino_swinb_cogcoor.pth
```

* ** Update @ 17th feb 2024: ** Trained weights available at https://huggingface.co/sunsmarterjieleaf/ChatterBox

2.2. Install Packages (HPC)

```Shell
module load compiler/cuda/11.0/compilervars
module load compiler/gcc/6.5.0/compilervars
conda create -n chatterbox python=3.11.5 
conda activate chatterbox
pip install --upgrade pip  # enable PEP 660 support
pip install -r requirements.txt
pip install deepspeed==0.11.1
unzip mmcv-1.4.7.zip
cd mmcv-1.4.7/
MMCV_WITH_OPS=1 pip install -e .
cd ../model/GroundingDINO/ops
python setup.py build install
wget https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha2/groundingdino_swinb_cogcoor.pth
git lfs install
git clone https://huggingface.co/liuhaotian/llava-llama-2-13b-chat-lightning-preview
```


## Train

* Train ChatterBox on 8xA800 GPUs (80GB).

<!-- ```
python startup_stage1.py  # stage1
python startup_stage2.py  # stage2
``` -->
```Shell
deepspeed --include localhost:0,1 --master_port 54906 train_stage1.py --version llava-llama-2-13b-chat-lightning-preview
deepspeed --include localhost:0,1 --master_port 54906 train_stage2.py --version llava-llama-2-13b-chat-lightning-preview
```



## Evaluation

See details at [evaluation](evaluation/readme.md).


## Demo

Coming soon


## Citation

If this project has been helpful or if you've used our dataset, please cite:
```
@article{tian2024chatterbox,
  title={ChatterBox: Multi-round Multimodal Referring and Grounding},
  author={Tian, Yunjie and Ma, Tianren and Xie, Lingxi and Qiu, Jihao and Tang, Xi and Zhang, Yuan and Jiao, Jianbin and Tian, Qi and Ye, Qixiang},
  journal={arXiv preprint arXiv:2401.13307},
  year={2024}
}
```

## Acknowledgment

This project is based on LLaVA ([paper](https://arxiv.org/abs/2304.08485), [code](https://github.com/haotian-liu/LLaVA)), LISA ([paper](https://arxiv.org/abs/2308.00692), [code](https://github.com/dvlab-research/LISA)), GPT4RoI ([paper](https://arxiv.org/abs/2307.03601), [code](https://github.com/jshilong/GPT4RoI)), thanks for their excellent works.
