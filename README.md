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

2. Install Packages (Runpod with template `2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04`)
```Shell
apt-get update
apt-get install zip unzip screen
pip install --upgrade pip
pip install -r requirements.txt
unzip mmcv-1.4.7.zip
cd mmcv-1.4.7/
MMCV_WITH_OPS=1 pip install -e .
cd ../model/GroundingDINO/ops
python setup.py build install
cd ../../../
cd llava-llama-2-13b-chat-lightning-preview
bash download_model.sh
cd ..
wget https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha2/groundingdino_swinb_cogcoor.pth
```

<!-- Downloading Visual Genome Grounding Datatset -->
<!-- rm -rf CB-300K
mkdir CB-300K && cd CB-300K
gdown --id 1vAqozQ3En5xSEIhzCp4WnUeWztYzZGQY
gdown --id 1C0XyMyhLRzdSDbtWAiGdW1rjljop0sMe
gdown --id 16CaLpXiiudAKP40ESKUjhquzWa0OTXaF
gdown --id 1--RcXrmY0yl4OFE-sDe_vZcbanJG5tUG
unzip images.zip
unzip images2.zip
rm *.zip
cd .. -->


* ** Update @ 17th feb 2024: ** Trained weights available at https://huggingface.co/sunsmarterjieleaf/ChatterBox

<!-- 3. Install Packages (HPC) -->
<!-- 
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
cd ../../../
wget https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha2/groundingdino_swinb_cogcoor.pth
git lfs install
git clone https://huggingface.co/liuhaotian/llava-llama-2-13b-chat-lightning-preview
``` -->


## Train

* Train ChatterBox on 8xA800 GPUs (80GB).

<!-- ```
python startup_stage1.py  # stage1
python startup_stage2.py  # stage2
``` -->
```Shell
deepspeed --include localhost:0,1 --master_port 54906 custom_train_gnd.py --version llava-llama-2-13b-chat-lightning-preview
```

<!-- deepspeed --include localhost:0,1 --master_port 54906 train_stage1.py --version llava-llama-2-13b-chat-lightning-preview
deepspeed --include localhost:0,1 --master_port 54906 train_stage2.py --version llava-llama-2-13b-chat-lightning-preview -->



## Evaluation

* Evaluate ChatterBox

```Shell
python eval_grounding.py --version llava-llama-2-13b-chat-lightning-preview --weight outputs_20Feb/epoch_0/global_step451/mp_rank_00_model_states.pt --images_path eval_gnd_data/ --gnd_file_path eval_gnd_data/grouding_qa.json --save_out_path eval_gnd_data/prediction.json
```

<!-- ```Shell
deepspeed --include localhost:0,1 --master_port 54906 eval_grounding.py \
--version llava-llama-2-13b-chat-lightning-preview \
--weight outputs/epoch_0/global_step201/mp_rank_00_model_states.pt \
--images_path eval_gnd_data/ \
--gnd_file_path eval_gnd_data/grouding_qa.json \
--save_out_path eval_gnd_data/prediction.json
```
 -->

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

Original Repository: [ChatterBox](https://github.com/sunsmarterjie/ChatterBox)
