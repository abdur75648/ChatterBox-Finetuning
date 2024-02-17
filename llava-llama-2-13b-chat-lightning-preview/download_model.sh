#!/bin/bash

# List of files to download
files=(
    "config.json"
    "generation_config.json"
    "pytorch_model.bin.index.json"
    "special_tokens_map.json"
    "tokenizer_config.json"
    "tokenizer.model"
    "mm_projector.bin"
    "pytorch_model-00001-of-00003.bin"
    "pytorch_model-00002-of-00003.bin"
    "pytorch_model-00003-of-00003.bin"
)


# Download all files using wget command form this remote rpeo in this forma (base_url)
# "https://huggingface.co/sunsmarterjieleaf/ChatterBox/resolve/main/llava-llama-2-13b-chat-lightning-preview/"+file+"?download=true"

base_url="https://huggingface.co/sunsmarterjieleaf/ChatterBox/resolve/main/llava-llama-2-13b-chat-lightning-preview/"

for file in "${files[@]}"; do
  wget -c "$base_url$file"
done