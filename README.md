# stimulus-eeg

## Setup
1. create a `.env` file based off of [.env.template](./.env.template)
1. create a file called `cert.pem` containing the contents from [this](https://github.com/Emotiv/cortex-example/blob/master/certificates/rootCA.pem)
1. install all [requirements](./requirements.txt)
1. install the [emotive launcher](https://www.emotiv.com/products/emotiv-launcher#download)
1. log into the emotiv launcher. this is a background app that acts as a wss server
1. run [`ORE_EGG_2.py`](./ORE_EEG_2.py)
1. on the first time running this script, use the emotiv launcher to accept access from the headset
