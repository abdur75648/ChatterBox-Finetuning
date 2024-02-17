python eval_grounding.py \
--version /path/to/llava-llama-2-13b-chat-lightning-preview \
--weight /path/to/chatterbox_grounding_ckp.pt \
--vision-tower openai/clip-vit-large-patch14 \
--vision_tower_aux openai/clip-vit-large-patch14 \
--coco2017_path /path/to/MSCOCO2017/images/ \
--coco_val_path /path/to/grouding_qa.json \
--save_out_path /save_path/predict_grounding.json \
--pretrained groundingdino_swinb_cogcoor.pth

