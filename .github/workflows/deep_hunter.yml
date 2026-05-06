name: Deep Web Hunter (LLM Scraper)

on:
  # This allows us to click a button in GitHub to run it manually
  workflow_dispatch: 

jobs:
  hunt:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          # This installs the invisible Chrome browser + system dependencies
          playwright install --with-deps chromium
          
      - name: Unleash the LLM
        env:
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
        run: python deep_hunter.py
