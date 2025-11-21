# ---- Base Image ----
FROM python:3.10-slim

# ---- System dependencies ----
# Necesarios para Selenium, PIL y otros procesamientos
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    chromium-driver \
    chromium \
    libgl1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ---- Python venv (opcional) ----
# Puedes evitarlo, pero mantiene organizado el entorno
ENV VENV_PATH="/opt/venv"
RUN python3 -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# ---- Working directory ----
WORKDIR /app

# ---- Copy only requirements first (cache optimization) ----
COPY requirements.txt ./requirements.txt

# ---- Install dependencies ----
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# ---- Copy source code ----
COPY scraper_dataset.py ./
COPY etl_pipeline.py ./
COPY dedupe_by_hash.py ./
COPY preprocess_resize.py ./
COPY split_dataset.py ./
COPY check_corrupt.py ./
COPY fast_download.py ./
COPY fast_download_transistor.py ./
COPY metadata.csv ./

# ---- Create dataset directories ----
RUN mkdir -p dataset dataset_preprocessed dataset_split

# ---- Default command ----
# Puedes cambiarlo al script que quieras ejecutar dentro del contenedor
CMD ["bash"]
