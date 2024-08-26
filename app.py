import datetime
import os
import uuid

import re
import json
import flask
import flask_moment
import sqlite3

from jinja2 import Template

DATASETS = os.getenv("DATASETS", "data")
DBFILE = os.getenv("DBFILE", "data/downloads.sqlite")
EXTRA_TIME = os.getenv("EXTRA_TIME", "+1 day")
PASSWORD = os.getenv("PASSWORD", "secret")
READ_SIZE = 4096

app = flask.Flask(__name__)
moment = flask_moment.Moment(app)
connect = sqlite3.connect(DBFILE)
connect.execute(
    f'CREATE TABLE IF NOT EXISTS DOWNLOADS (\
      id TEXT, \
      dataset TEXT, \
      title TEXT, \
      name TEXT, \
      email TEXT, \
      affiliation TEXT, \
      created DATE DEFAULT (datetime(CURRENT_TIMESTAMP)), \
      expires DATE DEFAULT (datetime(CURRENT_TIMESTAMP, \'{EXTRA_TIME}\')), \
      CONSTRAINT id_pk PRIMARY KEY (id))')


def load_data():
    with open(f"{DATASETS}/datasets.json", "r") as fp:
        return json.load(fp)
    return {}

def create_schema(dataset):
    data = load_data()
    if dataset not in data:
        return flask.redirect('/')
    var = "hello"
    schema_string = f"""
    <script type="application/ld+json">
    {{
      "@context":"https://schema.org/",
      "@type":"Dataset",
      "name": {data[dataset]['title']},
      "description": {re.sub("<.*>", "",data[dataset]['description'])},
      "url":"https://data.aifarms.org/view/{data[dataset]['title'].lower().replace(" ", "")}",
      "sameAs":
      "version":
      "isAccessibleForFree": true,
      "keywords": 
      "license": "https://data.aifarms.org/license/{data[dataset]['title'].lower().replace(" ", "")}",
      "identifier": {{
      }}
      "citation": {data[dataset]['citation']}
      "creator": [
        {{
          "@id": "",
          "@type": "Role",
          "roleName": "Author",
          "creator": {{
            "@id": "",
            "@type": "Person",
            "name": {data[dataset]['authors']}
          }}
        }}
      ],
      "provider": {{
        "@id": "",
        "@type": "",
        "legalName": ""
        "name": "",
        "url": ""
      }},
      "publisher": {{
        "@id": ""
      }}
    }}
    </script>
    """
    return schema_string

    #"keywords": {data[dataset]['keywords']}          (no keywords in dataset.json yet)





@app.get("/")
def home():
    data = load_data()
    kwargs = {
        "title": "AIFARMS Data Portal",
        "short_description": "Data gathered as part of AIFARMS that is publicly available.",
        "authors": "",
        "data": data
    }
    return flask.render_template("index.html", **kwargs)

def render_template(template, dataset):
    data = load_data()
    if dataset not in data:
        return flask.redirect('/')
    zipfile = f"{DATASETS}/{data[dataset]['uuid']}.zip"
    if os.path.exists(zipfile):
        filesize = sizeof_fmt(os.stat(zipfile).st_size)
    else:
        filesize = "N/A"
    keywords = set(["AIFARMS"])
    keywords.update(data[dataset].get("keywords", ""))
    return flask.render_template(template, dataset=dataset, filesize=filesize, keywords=keywords, **data[dataset])


@app.get("/view/<dataset>")
def view_dataset(dataset):
    return render_template("view.html", dataset=dataset)

@app.get("/ld/<dataset>")
def view_schema(dataset):
    data = load_data()
    if dataset not in data:
        return flask.redirect('/')
    schema_string = create_schema(dataset)
    rendered_schema = Template(schema_string).render(dataset=dataset)
    return flask.Response(rendered_schema, mimetype='text/plain')


@app.get("/croissant/<dataset>")
def croissant_dataset(dataset):
    return render_template("croissant.json", dataset=dataset)


@app.get("/citation/<dataset>")
@app.get("/cff/<dataset>")
def citation_dataset(dataset):
    return render_template("citation.cff", dataset=dataset)


@app.get("/license/<dataset>")
def license_dataset(dataset):
    data = load_data()
    if dataset not in data:
        return flask.redirect('/')
    rendered_license = Template(data[dataset]["license"]).render(**data[dataset])
    return flask.Response(rendered_license, mimetype='text/plain')


@app.route("/download/<dataset>", methods=["GET", "POST"])
def download_form(dataset):
    data = load_data()
    if dataset not in data:
        return flask.redirect('/')
    rendered_license = Template(data[dataset]["license"]).render(**data[dataset])

    if flask.request.method == "POST":
        title = flask.request.form.get('title', '').strip()
        name = flask.request.form.get('name', '').strip()
        if not name:
            return flask.render_template("download_form.html", rendered_license=rendered_license, **data[dataset])
        email = flask.request.form.get('email', '').strip()
        if not email:
            return flask.render_template("download_form.html", rendered_license=rendered_license, **data[dataset])
        affiliation = flask.request.form.get('affiliation', '').strip()
        license = flask.request.form.get('license', 'off')
        if license != 'on':
            return flask.render_template("download_form.html", rendered_license=rendered_license, **data[dataset])
        download_id = str(uuid.uuid1())

        with sqlite3.connect(DBFILE) as db:
            cursor = db.cursor()
            cursor.execute("INSERT INTO DOWNLOADS (id,dataset,title,name,email,affiliation) VALUES (?,?,?,?,?,?)",
                           (download_id, dataset, title, name, email, affiliation))
            db.commit()
        return flask.redirect(flask.url_for('download_dataset', dataset=dataset, id=download_id))
    else:
        return flask.render_template("download_form.html", rendered_license=rendered_license, **data[dataset])


def sizeof_fmt(num, suffix="B"):
    for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"


@app.get("/download/<dataset>/<id>")
def download_dataset(dataset, id):
    data = load_data()
    if dataset not in data:
        return flask.redirect('/')
    zipfile = f"{DATASETS}/{data[dataset]['uuid']}.zip"
    if not os.path.exists(zipfile):
        return flask.redirect('/')
    filesize = sizeof_fmt(os.stat(zipfile).st_size)

    download = {}
    with sqlite3.connect(DBFILE) as db:
        db.row_factory = sqlite3.Row
        cursor = db.cursor()
        cursor.execute("SELECT * FROM DOWNLOADS WHERE id=? AND dataset=?", (id, dataset))
        download = cursor.fetchall()
    if not download or len(download) != 1:
        return flask.redirect('/')
    download = download[0]
    expires = datetime.datetime.strptime(download['expires'], '%Y-%m-%d %H:%M:%S')
    if expires < datetime.datetime.now():
        return flask.redirect('/')

    url = flask.url_for('download_zip', dataset=dataset, id=id, _scheme="https", _external=True)
    return flask.render_template("download_dataset.html",
                                 url=url, expires=expires, download=download, filesize=filesize,
                                 **data[dataset])


@app.get("/download/<dataset>/<id>.zip")
def download_zip(dataset, id):
    data = load_data()
    if dataset not in data:
        return flask.redirect('/')
    zipfile = f"{DATASETS}/{data[dataset]['uuid']}.zip"
    if not os.path.exists(zipfile):
        return flask.redirect('/')
    if os.path.exists(zipfile):
        filesize = sizeof_fmt(os.stat(zipfile).st_size)
    else:
        filesize = "N/A"

    download = {}
    with sqlite3.connect(DBFILE) as db:
        db.row_factory = sqlite3.Row
        cursor = db.cursor()
        cursor.execute("SELECT * FROM DOWNLOADS WHERE id=? AND dataset=?", (id, dataset))
        download = cursor.fetchall()
    if not download or len(download) != 1:
        return flask.redirect('/')
    download = download[0]
    expires = datetime.datetime.strptime(download['expires'], '%Y-%m-%d %H:%M:%S')
    if expires < datetime.datetime.now():
        return flask.redirect('/')

    return flask.send_from_directory(DATASETS, f"{data[dataset]['uuid']}.zip", 
                                     as_attachment=True, download_name=f"{dataset}.zip")
    # def generate():
    #     with open(zipfile, "rb") as fp:
    #         data = fp.read(READ_SIZE)
    #         while data:
    #             yield data
    #             data = fp.read(READ_SIZE)
    # return flask.Response(generate(), mimetype='application/x-zip')


@app.get("/downloads")
def downloads():
    password = flask.request.args.get('password')
    if password != PASSWORD:
        return flask.redirect('/')

    downloads = []
    with sqlite3.connect(DBFILE) as db:
        db.row_factory = sqlite3.Row
        cursor = db.cursor()
        cursor.execute("SELECT * FROM DOWNLOADS")
        downloads = cursor.fetchall()

    return flask.render_template("downloads.html",
                                 title="Downloads", short_decription="List of all downloads", downloads=downloads)


if __name__ == "__main__":
    app.run(debug=True)
