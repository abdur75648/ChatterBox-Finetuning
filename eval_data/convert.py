import os, re, json, cv2, shutil, cv2
import matplotlib.pyplot as plt
from tqdm import tqdm

# json_files_all = sorted([f for f in os.listdir() if f.endswith('.json')])
json_file = "data1.1.json"
class_names = ['icon', 'column', 'button', 'tab', 'textbox']

# for json_file in json_files_all:
print("Processing: ", json_file)
with open(json_file) as f:
    dataset = json.load(f)
print("Dataset size: ", len(dataset))

new_data_dict = {"data": []}
for i, data in enumerate(tqdm(dataset)):
    bbox = re.findall(r"\[.*?\]", data["Question"])
    assert len(bbox) == 0, f"Invalid question: {data['Question']}"
    
    raw_answer = data["Answer"]
    bbox = re.findall(r"\[.*?\]", data["Answer"])
    assert len(bbox)==1, f"Invalid bounding box in answer: {data['Answer']}"
    bbox = bbox[0]
    
    left_part = data["Answer"].split(bbox)[0]
    right_part = data["Answer"].split(bbox)[1]
    right_part = right_part.replace(".", "").strip()
    assert right_part in class_names, "Class not found: ->" + right_part
    current_bbox_class = right_part
    
    bbox = bbox.replace("[", "").replace("]", "")
    if "," in bbox:
        bbox = bbox.split(",")
    else:
        bbox = bbox.split(" ")
    assert len(bbox) == 4
    img = cv2.imread(data["imagePath"])
    bbox = [float(x) for x in bbox]
    bbox = [int(bbox[0]*img.shape[1]), int(bbox[1]*img.shape[0]), int(bbox[2]*img.shape[1]), int(bbox[3]*img.shape[0])]
    bbox_str = ", ".join([str(x) for x in bbox])
    bbox_str_with_class = f" <{current_bbox_class}: [{bbox_str}]>"
    
    new_sample = {
        "id": str(i),
        "image": data["imagePath"],
        "image_wh": [img.shape[1], img.shape[0]],
        "conversation": [
            {
                "from": "human",
                "value": data["Question"]
            },
            {
                "from": "gpt",
                "value": left_part + " " + current_bbox_class + "." + bbox_str_with_class
            }
        ]
    }
    new_data_dict["data"].append(new_sample)
new_json_file = json_file.split(".json")[0] + "_updated.json"
with open(new_json_file, 'w') as f:
    json.dump(new_data_dict, f, indent=4)