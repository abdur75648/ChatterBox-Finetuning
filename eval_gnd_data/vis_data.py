import json
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Load the JSON file
file_path = "prediction.json"
with open(file_path) as f:
    data = json.load(f)

# Function to visualize gt_box for a given sample index
def visualize_gt_box(sample_index):
    sample = data[sample_index]
    filename = sample["image_abs_path"]
    filename = filename.split("/")[-1]
    gt_box = sample["gt"]
    pred_box = sample["out_boxes"]
    print(f"Ground Truth Box: {gt_box}") # x1, y1, x`2, y2
    print(f"Predicted Box: {pred_box}") # x1, y1, x`2, y2
    print("Answer: ", sample["answer"])

   # Read the image and Create a rectangle patch for the gt_box in green color and pred_box in blue color
    img = plt.imread(filename)
    fig, ax = plt.subplots(1)
    ax.imshow(img)
    rect_gt = patches.Rectangle((gt_box[0], gt_box[1]), gt_box[2]-gt_box[0], gt_box[3]-gt_box[1], linewidth=2, edgecolor='g', facecolor='none')
    rect_pred = patches.Rectangle((pred_box[0], pred_box[1]), pred_box[2]-pred_box[0], pred_box[3]-pred_box[1], linewidth=2, edgecolor='b', facecolor='none')
    
    # Add the rectangle patch to the Axes
    ax.add_patch(rect_gt)
    ax.add_patch(rect_pred)

    # Save the plot
    plt.savefig(f"vis_"+filename)

sample_index = 0
visualize_gt_box(sample_index)
