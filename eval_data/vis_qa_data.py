import json
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Load the JSON file
file_path = "data2.2.json"
with open(file_path) as f:
    data = json.load(f)

# Function to visualize gt_box for a given sample index
def visualize_gt_box(sample_index):
    sample = data[sample_index]
    filename = sample["filename"]
    gt_box = sample["gt_box"]
    print(f"Ground Truth Box: {gt_box}") # x1, y1, x`2, y2
    print("Question: ", sample["question"])
    print("Answer: ", sample["answer"])

   # Read the image and Create a rectangle patch for the gt_box in green color and pred_box in blue color
    img = plt.imread(filename)
    # assert sample["wh"] == [img.shape[1], img.shape[0]]
    
    fig, ax = plt.subplots(1)
    ax.imshow(img)
    rect_gt = patches.Rectangle((gt_box[0], gt_box[1]), gt_box[2]-gt_box[0], gt_box[3]-gt_box[1], linewidth=2, edgecolor='g', facecolor='none')
    
    # Add the rectangle patch to the Axes
    ax.add_patch(rect_gt)

    # Save the plot
    plt.savefig(f"vis_"+filename.replace("/", "_"))

for sample_index in range(len(data)):
    visualize_gt_box(sample_index)
