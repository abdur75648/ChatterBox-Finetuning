from huggingface_hub import hf_hub_download

repo_id = "sunsmarterjieleaf/ChatterBox"
directory_name = "llava-llama-2-13b-chat-lightning-preview"
# download the above directory from the repo in the current working directory
hf_hub_download(repo_id, directory_name, cache_dir=".")