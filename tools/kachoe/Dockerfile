# The kachō-e art pipeline in a box: species list -> seeds -> Gemini -> cutouts.
# Built and run for you by `birdlistener art --docker`; by hand:
#
#   docker build -t bird-listener-art tools/kachoe
#   docker run --rm -it \
#     -v "$PWD:/repo" -v "$HOME/.u2net:/root/.u2net" \
#     -e GEMINI_API_KEY \
#     bird-listener-art python3 tools/kachoe/run_pipeline.py --from-json /repo/range.json
#
# The repo is mounted at /repo so illustrations/, refs/ and wall-node/cutouts/
# land in your checkout; ~/.u2net caches the 1 GB BiRefNet model across runs.
FROM python:3.12-slim
WORKDIR /repo
RUN apt-get update && apt-get install -y --no-install-recommends rsync openssh-client curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONUNBUFFERED=1
CMD ["python3", "tools/kachoe/run_pipeline.py", "--help"]
