# L3 Body Composition app - runs on any computer with Docker (Windows, Mac, Linux).
#
# Build + start:   docker compose up -d --build      (first build downloads ~4 GB, 10-30 min)
# Open:            http://localhost:8000
#
# CPU build by default. For an NVIDIA GPU see docker-compose.gpu.yml.
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# 1. PyTorch: CPU wheel (small) by default. GPU: build with TORCH_INDEX=https://download.pytorch.org/whl/cu121
 ARG TORCH_VARIANT=cpu
 RUN pip install --upgrade pip && pip install "torch==2.5.1+${TORCH_VARIANT}" "torchvision==0.20.1+${TORCH_VARIANT}" --extra-index-url https://download.pytorch.org/whl/${TORCH_VARIANT} && pip freeze | grep -iE "^(torch|torchvision)==" > /tmp/torch-lock.txt
# 2. the rest of the Python packages
COPY docker/requirements.txt /tmp/requirements.txt
   RUN pip install -r /tmp/requirements.txt -c /tmp/torch-lock.txt
# 3. model weights, baked into the image so it works offline
ENV TOTALSEG_HOME_DIR=/opt/models/totalsegmentator \
    L3_MODEL=/opt/models/Task927_FatMuscle/nnUNetTrainerV2__nnUNetPlansv2.1
COPY docker/download_models.py /opt/download_models.py
RUN python /opt/download_models.py totalseg
RUN python /opt/download_models.py musclefat

# 4. the app
COPY l3_analysis.py /app/l3_analysis.py
COPY l3_app /app/l3_app

# nnU-Net v1 wants these set (only to silence warnings; the model path is given directly)
ENV nnUNet_raw_data_base=/tmp/nnunet_raw \
    nnUNet_preprocessed=/tmp/nnunet_pre \
    RESULTS_FOLDER=/tmp/nnunet_results \
    MPLBACKEND=Agg \
    L3_SCRIPT=/app/l3_analysis.py \
    L3_JOBS=/data \
    L3_PORT=8000

VOLUME /data
EXPOSE 8000
WORKDIR /app/l3_app
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/jobs', timeout=4)" || exit 1
CMD ["python", "app.py"]
