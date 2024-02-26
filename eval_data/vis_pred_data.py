import json
import cv2
from PIL import Image, ImageDraw
# Load the JSON file
file_path = "pred_2.2.json"
with open(file_path) as f:
    data = json.load(f)

# Function to visualize gt_box for a given sample index
def visualize_gt_box(sample_index):
    sample = data[sample_index]
    filename = sample["image_abs_path"]
    # Update filename to only everything except the first part of the path
    filename = '/'.join(filename.split('/')[1:])
    if "gt" not in sample:
        sample["gt"] = []
    gt_box = sample["gt"]
    pred_box = sample["out_boxes"]
    print("="*50)
    print(f"Image: {filename}")
    print(f"Question: {sample['prompt']}")
    # print(f"Ground Truth Box: {gt_box}") # x1, y1, x`2, y2
    print(f"Predicted Box: {pred_box}") # x1, y1, x`2, y2
    print("Answer: ", sample["answer"])

    # Read the image using OpenCV
    img = cv2.imread(filename)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_pil = Image.fromarray(img_rgb)

    draw = ImageDraw.Draw(img_pil)
    if len(gt_box) > 0:
        draw.rectangle([(gt_box[0], gt_box[1]), (gt_box[2], gt_box[3])], outline='green', width=5)
    
    draw.rectangle([(pred_box[0], pred_box[1]), (pred_box[2], pred_box[3])], outline='blue', width=5)

    filename = filename.replace("/", "_")
    # Save the image
    img_pil.save(f"vis_{filename}")

for sample_index in range(len(data)):
    print("="*50)
    visualize_gt_box(sample_index)
    print("="*50)
