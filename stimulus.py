from psychopy import visual, core, event, gui, logging
from psychopy.monitors import Monitor
from psychopy.clock import Clock

import os
from scipy.io import loadmat
from PIL import Image
import random
import asyncio
from asyncio import Queue
import pathlib
import websockets # pip install websocket-client
import json
import ssl
import os
import time
from dotenv import load_dotenv # pip install python-dotenv
import h5py
import numpy as np

# Placeholder function for EEG setup and trigger recording
load_dotenv(override=True)
IMAGE_PATH = "/Volumes/Rembr2Eject/nsd_stimuli.hdf5"
# IMAGE_PATH = "stimulus/nsd_stimuli.hdf5"
EXP_PATH = "stimulus/nsd_expdesign.mat"
EMOTIV_ON = True
headset_info = {} # update this with the headset info

# Networking
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
localhost_pem = pathlib.Path(__file__).with_name("cert.pem")
ssl_context.load_verify_locations(localhost_pem)

# Clock
experiment_start_time = time.time()
global_clock = Clock()
global_clock.reset()

async def send_message(message, websocket):
    attempt = 0
    retries = 3
    while attempt < retries:
        try:
            message_json = json.dumps(message)
            await websocket.send(message_json)
            response = await websocket.recv()
            return json.loads(response)
        except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.WebSocketException) as e:
            attempt += 1
            print(f"Attempt {attempt}: Failed to communicate with WebSocket server - {e}")
            if attempt >= retries:
                print("Maximum retry attempts reached. Stopping.")
                return {}
            await asyncio.sleep(1)  # Wait a bit before retrying
    return {}

async def setup_eeg(websocket):
    # Initialize EEG, e.g., with Emotiv SDK
    # This function needs to be implemented based on your EEG SDK's documentation
    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "requestAccess",
        "params": {
            "clientId": os.environ.get('CLIENT_ID'),
            "clientSecret": os.environ.get('CLIENT_SECRET'),
        }
    }, websocket)
    # give it access through launcher
    # refresh the device list
    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "controlDevice",
        "params": {
            "command": "refresh"
        }
    }, websocket)
    # query the headsets
    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "queryHeadsets"
    }, websocket)
    if len(response["result"]) == 0:
        print("No headsets found")
        exit(1)
    # connect to the headset
    headset = response["result"][0]["id"] # assuming the first headset, otherwise can manually specifiy
    with open('mapping.json', 'r') as file:
        mapping = json.load(file)
    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "controlDevice",
        "params": {
            "command": "connect",
            "headset": headset,
            "mappings": mapping
        }
    }, websocket)
    response = await send_message({ # authorize the connection
        "id": 1,
        "jsonrpc": "2.0",
        "method": "authorize",
        "params": {
            "clientId": os.environ.get('CLIENT_ID'),
            "clientSecret": os.environ.get('CLIENT_SECRET'),
            "debit": 1000
        }
    }, websocket)
    if "error" in response:
        error = response["error"]
        print(f"Error in authorizing {error}") # if it gets here, probably didn't set up env variables correctly
        exit(1)
    cortex_token = response["result"]["cortexToken"]
    # Liscense info
    # response = await send_message({
    #     "id": 1,
    #     "jsonrpc": "2.0",
    #     "method": "getLicenseInfo",
    #     "params": {
    #         "cortexToken": cortex_token
    #     }
    # }, websocket)
    # sometimes requires a delay after authorizing and creating a session
    await asyncio.sleep(0.2)
    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "createSession",
        "params": {
            "cortexToken": cortex_token,
            "headset": headset,
            "status": "open"
        }
    }, websocket)
    session_id = response["result"]["id"]
    print("created session", session_id)

    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "updateSession",
        "params": {
            "cortexToken": cortex_token,
            "session": session_id,
            "status": "active"
        }
    }, websocket)

    headset_info["headset"] = headset
    headset_info["cortex_token"] = cortex_token
    headset_info["session_id"] = session_id
    headset_info["record_ids"] = []


    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "querySessions",
        "params": {
            "cortexToken": cortex_token,
        }
    }, websocket)


async def teardown_eeg(websocket, subj, session):
    await asyncio.sleep(1)
    response = await send_message({
        "id": 2,
        "jsonrpc": "2.0",
        "method": "updateSession",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "session": headset_info["session_id"],
            "status": "close"
        }
    }, websocket)
    # print("session closed:", response)
    await asyncio.sleep(1)
    response = await send_message({
        "id": 3,
        "jsonrpc": "2.0",
        "method": "controlDevice",
        "params": {
            "command": "disconnect",
            "headset": headset_info["headset"]
        }
    }, websocket)
    # print("headset disconnected:", response)
    await asyncio.sleep(1)

    # Save to output directory
    output_path = os.path.join("recordings", "subj_" + subj, "session_" + session)
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_path)
    print("saving to directory:", output_path)

    response = await send_message({
        "id": 5,
        "jsonrpc": "2.0",
        "method": "exportRecord",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "folder": output_path,
            "format": "EDFPLUS",
            "recordIds": headset_info["record_ids"],
            "streamTypes": [
                "EEG",
                "MOTION"
            ]
        }
    }, websocket)
    print("export record response:", response)


async def create_record(subj, session, websocket):
    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "createRecord",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "session": headset_info["session_id"],
            "title": f"Subject {subj}, Session {session} Recording"
        }
    }, websocket)
    record_id = response["result"]["record"]["uuid"]
    headset_info["record_id"] = record_id
    headset_info["record_ids"].append(record_id)
    
    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "querySessions",
        "params": {
            "cortexToken": headset_info["cortex_token"],
        }
    }, websocket)


async def stop_record(websocket):
    if not headset_info["record_id"]:
        return

    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "stopRecord",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "session": headset_info["session_id"]
        }
    }, websocket)
    print("stopping record:", response)


async def record_trigger(message, websocket, debug_mode=False):
    if debug_mode:
        logging.log(level=logging.DATA, msg=f"Trigger recorded: {message['label']} {message['value']}")
    else:
        await send_message({
            "id": 1,
            "jsonrpc": "2.0",
            "method": "injectMarker",
            "params": {
                "cortexToken": headset_info["cortex_token"],
                "session": headset_info["session_id"],
                "time": message['time'],
                "label": message['label'],
                "value": message['value']
            }
        }, websocket)


message_queue = Queue()
async def process_triggers(websocket):
    """Continuously receive and add messages to the queue."""
    while True:
        message = await message_queue.get()
        if message is None:
            break
        await record_trigger(message, websocket, False)
        message_queue.task_done()


def validate_block(block_trials):
    prev = -1
    for trial in block_trials:
        if trial == prev:
            return False
        prev = trial
    return True


def create_trials(n_images, n_oddballs, num_blocks):
    trials = []

    for block in range(num_blocks):
        isValidBlock = False
        block_trials = []
        while not isValidBlock:
            # Generate trials for each block
            start = block * n_images + 1
            end = start + n_images
            images = list(range(start, end))
            oddballs = [-1] * n_oddballs
            block_trials = images + oddballs
            random.shuffle(block_trials)
            # ensure no two consecutive trials are the same.
            # legacy code when we repeated images in a block
            isValidBlock = validate_block(block_trials)

        for idx, trial in enumerate(block_trials):
            trials.append({'block': (block + 1), 'image': trial, 'end_of_block': (idx == len(block_trials) - 1)})

    return trials


def display_instructions(window, session_number):
    instruction_text = (
        f"Welcome to session {session_number} of the study.\n\n"
        "In this session, you will complete a perception task.\n"
        "This session consists of 16 experimental blocks.\n\n"
        "You will see sequences of images appearing on the screen, your task is to "
        "press the space bar when you see an image appear twice in a row.\n\n"
        "When you are ready, press the space bar to start."
    )

    # Assuming a window width of 800 pixels, adjust this based on your actual window size
    # Use 80% of window width for text wrapping
    wrap_width = window.size[0] * 0.8

    message = visual.TextStim(window, text=instruction_text, pos=(0, 0), color=(1, 1, 1), height=40, wrapWidth=wrap_width)
    message.draw()
    window.flip()
    event.waitKeys(keyList=['space'])

def getImages(subj, session, n_images, num_blocks):
    totalImages = n_images * num_blocks
    # Mapping from integer id to NSD id
    mat = loadmat(EXP_PATH)
    subjectim = mat['subjectim'] # 1-indexed
    sessionGroup = (int(session)-1) % 3
    image_indices = subjectim[int(subj)-1][sessionGroup*totalImages : (sessionGroup + 1)*totalImages]
    image_indices = image_indices -1 # img_map is 1-indexed
    sorted_indices = np.argsort(image_indices)
    inverse_indices = np.argsort(sorted_indices)  # To revert back to original order

    with h5py.File(IMAGE_PATH, 'r') as file:
        dataset = file["imgBrick"]
        sorted_images = dataset[image_indices[sorted_indices], :, :, :]  # Assuming index is within the valid range for dataset # pyright: ignore
        images = sorted_images[inverse_indices]
        pil_images = [Image.fromarray(img) for img in images]
    return pil_images

async def run_experiment(trials, window, websocket, subj, session, n_images, num_blocks, img_width, img_height):
    last_image = None
    # Initialize an empty list to hold the image numbers for the current block
    image_sequence = []
    images = getImages(subj, session, n_images, num_blocks)
    print(subj, session, n_images, num_blocks)

    # Create a record for the session
    current_block = 1  # Initialize the current block counter
    start_index = (current_block - 1) * n_images
    end_index = start_index + n_images

    # Register the callback function for space presses
    # keyboard.on_press(on_space_press)

    if EMOTIV_ON:
        await create_record(subj, session, websocket)
    for idx, trial in enumerate(trials):
        if trial['block'] != current_block:
            current_block = trial['block']
            start_index = (current_block - 1) * n_images
            end_index = start_index + n_images
            # print(f"\nBlock {current_block}, Start Index: {start_index}")
            # print(f"Block {current_block}, End Index: {end_index}\n")
        
        # Check if this trial is an oddball
        is_oddball = (trial['image'] == -1)
        if is_oddball:
            image = last_image
        else:
            image = images[trial['image'] - 1] # Recall that trial and img_map is 1-indexed
            last_image = image

        
        # Append current image number to the sequence list
        image_sequence.append(trial['image'])

        # Logging the trial details
        # print(f"Block {trial['block']}, Trial {idx + 1}: Image {trial['image']} {'(Oddball)' if is_oddball else ''}")

        # Prepare the image
        image_stim = visual.ImageStim(win=window, image=image, pos=(0, 0), size=(img_width, img_height))
        image_stim.draw()
        # Send trigger
        await message_queue.put({'label': 'stim', 'value': trial['image'] if not is_oddball else 100000, 'time': time.time() * 1000})
        # Display the image
        window.flip()
        await asyncio.sleep(0.3)

        # Rest screen with a fixation cross
        display_cross_with_jitter(window, 0.3, 0.05)

        keys = event.getKeys(keyList=["escape", "space"], timeStamped=global_clock)

        escape_pressed = False
        space_pressed = False
        space_time = None
        for key, timestamp in keys:
            if key == "escape":
                escape_pressed = True
            elif key == "space":
                space_pressed = True
                space_time = (experiment_start_time + timestamp) * 1000
        
        if escape_pressed: # Terminate experiment early if escape is pressed
            print("Experiment terminated early.")
            break

        # Record behavioural data (if space is or is not pressed with the oddball/non-oddball image)
        if not is_oddball and not space_pressed:
            # print("No oddball, no space")
            await message_queue.put({'label': 'behav', 'value': 0, 'time': time.time() * 1000})
        elif not is_oddball and space_pressed:
            # print("No oddball, space")
            await message_queue.put({'label': 'behav', 'value': 1, 'time': space_time})
        elif is_oddball and space_pressed:
            # print("Oddball, space")
            await message_queue.put({'label': 'behav', 'value': 2, 'time': space_time})
        elif is_oddball and not space_pressed:
            # print("Oddball, no space")
            await message_queue.put({'label': 'behav', 'value': 3, 'time': time.time() * 1000})

        # Check if end of block
        if trial['end_of_block']:
            # Print the image sequence for the current block
            print(f"\nEnd of Block {trial['block']} Image Sequence: \n {', '.join(map(str, image_sequence))}")
            # Clear the list for the next block
            image_sequence = []

            # Display break message at the end of each block
            display_break_message(window, trial['block'])

            # Create a new record for the next block
            current_block += 1
            start_index = (current_block - 1) * n_images
            end_index = start_index + n_images
            print(f"\nBlock {current_block}, Start Index: {start_index}")
            print(f"Block {current_block}, End Index: {end_index}\n")

    # Stop the consumer task
    await message_queue.put(None)


def display_break_message(window, block_number):
    message = f"You've completed block {block_number}.\n\nTake a little break and press the space bar when you're ready to continue to the next block."
    break_message = visual.TextStim(window, text=message, pos=(0, 0), color=(1, 1, 1), height=40, wrapWidth=window.size[0] * 0.8)
    break_message.draw()
    window.flip()
    event.waitKeys(keyList=['space'])


def display_completion_message(window):
    completion_text = "Congratulations! You have completed the experiment.\n\nPress the space bar to exit."
    completion_message = visual.TextStim(window, text=completion_text, pos=(0, 0), color=(1, 1, 1), height=40, wrapWidth=window.size[0] * 0.8)
    completion_message.draw()
    window.flip()
    event.waitKeys(keyList=['space'])


def display_cross_with_jitter(window, base_time, jitter):
    rest_period = base_time + random.randint(0, int(jitter * 100)) / 100.0
    fixation_cross = visual.TextStim(window, text='+', pos=(0, 0), color=(1, 1, 1), height=40)
    fixation_cross.draw()
    window.flip()
    core.wait(rest_period)


async def main():
    # Experiment setup
    # TODO: Fix order to be subject, session
    participant_info = {'Subject': '', 'Session': ''}
    dlg = gui.DlgFromDict(dictionary=participant_info, title='Experiment Info')

    if not dlg.OK:
        core.quit()

    # Monitor setup
    my_monitor = Monitor(name='Q27q-1L')
    my_monitor.setWidth(61.42)       # Monitor width in centimeters (physical size of screen)
    my_monitor.setDistance(80)    # Viewing distance in centimeters
    my_monitor.setSizePix((2560, 1440))  # Resolution in pixels
    my_monitor.save()

    # Default
    window = visual.Window(fullscr=True, color=[0, 0, 0], units='pix')
    # Lenovo external monitor   
    # window = visual.Window(screen=1, monitor="Q27q-1L", fullscr=True, size=(2560, 1440), color=(0, 0, 0), units='pix')

    # Parameters
    n_images = 208  # Number of unique images per block
    n_oddballs = 24  # Number of oddball images per block
    num_blocks = 8  # Number of blocks
    img_width, img_height = 425, 425  # Define image dimensions
    window_size = window.size

    # Display instructions
    display_instructions(window, participant_info['Session'])

    # Setup EEG
    async with websockets.connect("wss://localhost:6868", ssl=ssl_context) as websocket:
        if EMOTIV_ON:
            await setup_eeg(websocket)
        trials = create_trials(n_images, n_oddballs, num_blocks)
        
        # Run the experiment
        if EMOTIV_ON:
            experiment_task = asyncio.create_task(run_experiment(trials, window, websocket, participant_info['Subject'], participant_info['Session'], n_images, num_blocks, img_width, img_height))
            recording_task = asyncio.create_task(process_triggers(websocket))
            await asyncio.gather(experiment_task, recording_task)
        else: 
            await run_experiment(trials, window, websocket, participant_info['Subject'], participant_info['Session'], n_images, num_blocks, img_width, img_height)

        # Wind down and save results
        if EMOTIV_ON:
            await stop_record(websocket)
            await teardown_eeg(websocket, participant_info['Subject'], participant_info['Session'])
        # Display completion message
        display_completion_message(window)

        window.close()
        core.quit()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
    #asyncio.run(main())
