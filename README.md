# NSE Master Scanner Pro

## Deploy to Streamlit Community Cloud (Free)

### Step 1 — Upload to GitHub
1. Create a free account at https://github.com
2. Create a new repository (e.g. `nse-scanner`)
3. Upload all 4 files:
   - `app.py`
   - `nse500.py`
   - `requirements.txt`
   - `.streamlit/config.toml`

### Step 2 — Deploy on Streamlit Cloud
1. Go to https://share.streamlit.io
2. Sign in with your GitHub account
3. Click **New app**
4. Select your repository and set:
   - **Branch:** main
   - **Main file:** app.py
5. Click **Deploy**

### Done!
You'll get a free public URL like:
`https://your-username-nse-scanner-app-xxxx.streamlit.app`

Open it from any device, any network, anywhere.

## Local run (optional)
```
pip install -r requirements.txt
streamlit run app.py
```
