FROM python:3.11

EXPOSE 8000
ENV DATASETS="data" \
    DBFILE="data/downloads.sqlite" \
    EXTRA_TIME="+7 days" \
    PASSWORD="secret"

WORKDIR /src
COPY requirements.txt /src
RUN pip3 install -Ur requirements.txt

COPY . /src
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0", "--worker-class", "gevent", "--timeout", "14400", "app:app"]
