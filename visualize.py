import mne

filePath = "recordings/subj_1/session_1/Subject 1, Session 1 Recording_EPOCFLEX_213075_2024.05.06T11.48.41.07.00.edf"
raw = mne.io.read_raw_edf(filePath, preload=True)

raw.plot()