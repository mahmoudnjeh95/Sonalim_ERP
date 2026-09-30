FROM python:3.12-slim-trixie

# OMP_NUM_THREADS is set in compose.yaml, next to the service's `cpus: 2`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# trixie renamed libglib2.0-0 to libglib2.0-0t64 (64-bit time_t transition).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0t64 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# rapidocr also pulls opencv-python (the GUI build, which needs libGL); both wheels unpack
# into the same cv2 folder, so drop it and let the pinned headless build own cv2.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir --force-reinstall --no-deps opencv-python-headless==5.0.0.93

COPY app ./app
COPY templates ./templates
# Load the models while building (rapidocr 3.9.2 ships them inside its wheel), so a broken
# install fails the build and the running container never needs the internet.
RUN python -c "from app.engine import Engine; from app.pipeline import TEMPLATES; assert TEMPLATES; Engine()"

EXPOSE 8100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
