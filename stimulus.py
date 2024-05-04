from psychopy import visual, core, event, gui, data, logging
import os
from scipy.io import loadmat
from PIL import Image
from tempfile import NamedTemporaryFile
import random
import asyncio
import pathlib
import websockets # pip install websocket-client
import json
import ssl
import os
import time
from dotenv import load_dotenv # pip install python-dotenv
import h5py
import scipy.io

# Placeholder function for EEG setup and trigger recording
load_dotenv()
IMAGE_PATH = "/Volumes/Rembr2Eject/nsd_stimuli.hdf5"
EXP_PATH = "stimulus/nsd_expdesign.mat"
headset_info = {} # update this with the headset info

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
localhost_pem = pathlib.Path(__file__).with_name("cert.pem")
ssl_context.load_verify_locations(localhost_pem)

async def send_message(message, websocket):
        message_json = json.dumps(message)
        await websocket.send(message_json)
        response = await websocket.recv()
        return json.loads(response)

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
    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "controlDevice",
        "params": {
            "command": "connect",
            "headset": headset,
            "mappings": { # under the assumption that the headset is an EPOC Flex
                "CMS": "F3",
                "DRL": "F5",
                "LA": "AF3",
                "LB": "AF7",
                "RA": "P8"
            }
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
    # sometimes requires a delay after authorizing and creating a session
    time.sleep(0.2)
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
    time.sleep(1)
    response = await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "controlDevice",
        "params": {
            "command": "disconnect",
            "headset": headset_info["headset"]
        }
    }, websocket)
    print("headset disconnected:", response)
    time.sleep(1)

    # Save to output directory
    output_path = os.path.join("recordings", "subj_" + subj, "session_" + session)
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_path)
    response = await send_message({
        "id": 5,
        "jsonrpc": "2.0",
        "method": "exportRecord",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "folder": output_path,
            "format": "EDF",
            "recordIds": headset_info["record_ids"],
            "streamTypes": [
                "EEG",
                "MOTION"
            ]
        }
    }, websocket)
    print("teardown response:", response)


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

    await send_message({
        "id": 1,
        "jsonrpc": "2.0",
        "method": "stopRecord",
        "params": {
            "cortexToken": headset_info["cortex_token"],
            "record": headset_info["record_id"],
        }
    }, websocket)


async def record_trigger(trigger_number, websocket, debug_mode=True):
    if debug_mode:
        logging.log(level=logging.DATA,
                    msg=f"Trigger recorded: {trigger_number}")
    else:
        response = await send_message({
            "id": 1,
            "jsonrpc": "2.0",
            "method": "injectMarker",
            "params": {
                "cortexToken": headset_info["cortex_token"],
                "session": headset_info["session_id"],
                "time": time.time() * 1000,
                "label": "TRIGGER",
                "value": trigger_number if trigger_number >= 0 else trigger_number * -100000
            }
        }, websocket)


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
            start = 1
            end = start + n_images
            images = list(range(start, end))
            oddballs = [-1] * n_oddballs
            block_trials = images + oddballs
            random.shuffle(block_trials)
            # ensure no two consecutive trials are the same
            isValidBlock = validate_block(block_trials)

        for idx, trial in enumerate(block_trials):
            trials.append({'block': (block + 1), 'trial': trial, 'end_of_block': (idx == len(block_trials) - 1)})

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

def getNsdIndices(subj, session):
    # Mapping from integer id to NSD id
    mat = scipy.io.loadmat(EXP_PATH)
    subjectim = mat['subjectim'] # 1-indexed
    image_indices = subjectim[int(subj)-1][(int(session)-1)*4000 : int(session)*4000]
    return image_indices

async def run_experiment(trials, window, websocket, subj, session, n_images, img_width, img_height):
    last_image = None
    # Initialize an empty list to hold the image numbers for the current block
    image_sequence = []
    img_map = getNsdIndices(subj, session)

    # Create a record for the session
    current_block = 1  # Initialize the current block counter
    start_index = (current_block - 1) * n_images
    end_index = start_index + n_images

    await create_record(subj, session, websocket)
    for idx, trial in enumerate(trials):
        if 'escape' in event.getKeys():
            print("Experiment terminated early.")
            break

        if trial['block'] != current_block:
            current_block = trial['block']
            start_index = (current_block - 1) * n_images
            end_index = start_index + n_images
            print(f"\nBlock {current_block}, Start Index: {start_index}")
            print(f"Block {current_block}, End Index: {end_index}\n")
        
        # Check if this trial is an oddball
        is_oddball = (trial['trial'] == -1)
        if is_oddball:
            image = last_image
        else:
            nsd_id = img_map[start_index + trial['trial'] - 1] # Recall that trial and img_map is 1-indexed
            # Adjust index for 0-based Python indexing
            with h5py.File(IMAGE_PATH, 'r') as file:
                dataset = file["imgBrick"]
                image = dataset[nsd_id-1, :, :, :]  # Assuming index is within the valid range for dataset
                image = Image.fromarray(image)
            last_image = image

        # Append current image number to the sequence list
        image_sequence.append(trial['trial'])

        # Logging the trial details
        print(f"Block {trial['block']}, Trial {idx + 1}: Image {trial['trial']} {'(Oddball)' if is_oddball else ''}")

        # Display the image
        image_stim = visual.ImageStim(win=window, image=image, pos=(0, 0), size=(img_width, img_height))
        image_stim.draw()
        window.flip()
        core.wait(0.3)  # Display time

        # Rest screen with a fixation cross
        display_cross_with_jitter(window, 0.3, 0.05)

        # Record a placeholder trigger
        # await record_trigger(99)
        await record_trigger(trial['trial'], websocket, debug_mode=False)

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
    participant_info = {'Subject': '', 'Session': '1'}
    dlg = gui.DlgFromDict(dictionary=participant_info, title='Experiment Info')
    if not dlg.OK:
        core.quit()

    # Setup window
    window = visual.Window(fullscr=False, color=[0, 0, 0], units='pix')

    # Display instructions
    display_instructions(window, participant_info['Session'])

    # Setup EEG
    async with websockets.connect("wss://localhost:6868", ssl=ssl_context) as websocket:
        await setup_eeg(websocket)

        # Parameters
        n_images = 10  # Number of unique images per block
        n_oddballs = 2  # Number of oddball images per block
        num_blocks = 16  # Number of blocks
        img_width, img_height = 425, 425  # Define image dimensions
        window_size = window.size

        trials = create_trials(n_images, n_oddballs, num_blocks)
        
        # Run the experiment
        await run_experiment(trials, window, websocket, participant_info['Subject'], participant_info['Session'], n_images, img_width, img_height)

        # Wind down and save results
        await stop_record(websocket)
        await teardown_eeg(websocket, participant_info['Subject'], participant_info['Session'])
        
        # Display completion message
        display_completion_message(window)

        window.close()
        core.quit()


if __name__ == '__main__':
    asyncio.run(main())
