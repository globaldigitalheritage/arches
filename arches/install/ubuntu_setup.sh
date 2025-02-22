#!/usr/bin/env bash

# For Ubuntu 16.04 (xenial) and 18.04 (bionic)

# Use the yes command if you would like to include java, postgis and node by default
# Example:
# yes | sudo ./ubuntu_setup.sh

function install_postgres {
  sudo add-apt-repository "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -sc)-pgdg main"
  wget --quiet -O - http://apt.postgresql.org/pub/repos/apt/ACCC4CF8.asc | sudo apt-key add -
  sudo apt-get update
  sudo apt-get install postgresql-9.6 postgresql-contrib-9.6 -y
  sudo apt-get install postgresql-9.6-postgis-2.4 -y
  sudo -u postgres psql -d postgres -c "ALTER USER postgres with encrypted password 'postgis';"
  sudo echo "*:*:*:postgres:postgis" >> ~/.pgpass
  sudo chmod 600 ~/.pgpass
  sudo chmod 666 /etc/postgresql/9.6/main/postgresql.conf
  sudo chmod 666 /etc/postgresql/9.6/main/pg_hba.conf
  sudo echo "standard_conforming_strings = off" >> /etc/postgresql/9.6/main/postgresql.conf
  sudo echo "listen_addresses = '*'" >> /etc/postgresql/9.6/main/postgresql.conf
  sudo echo "#TYPE   DATABASE  USER  CIDR-ADDRESS  METHOD" > /etc/postgresql/9.6/main/pg_hba.conf
  sudo echo "local   all       all                 trust" >> /etc/postgresql/9.6/main/pg_hba.conf
  sudo echo "host    all       all   127.0.0.1/32  trust" >> /etc/postgresql/9.6/main/pg_hba.conf
  sudo echo "host    all       all   ::1/128       trust" >> /etc/postgresql/9.6/main/pg_hba.conf
  sudo echo "host    all       all   0.0.0.0/0     md5" >> /etc/postgresql/9.6/main/pg_hba.conf
  sudo service postgresql restart

  sudo -u postgres psql -d postgres -c "CREATE EXTENSION postgis;"
  sudo -u postgres createdb -E UTF8 -T template0 --locale=en_US.utf8 template_postgis
  sudo -u postgres psql -d postgres -c "UPDATE pg_database SET datistemplate='true' WHERE datname='template_postgis'"
  sudo -u postgres psql -d template_postgis -c "CREATE EXTENSION postgis;"
  sudo -u postgres psql -d template_postgis -c "GRANT ALL ON geometry_columns TO PUBLIC;"
  sudo -u postgres psql -d template_postgis -c "GRANT ALL ON geography_columns TO PUBLIC;"
  sudo -u postgres psql -d template_postgis -c "GRANT ALL ON spatial_ref_sys TO PUBLIC;"
  sudo -u postgres createdb training -T template_postgis
}

function install_couchdb {
  sudo add-apt-repository "deb https://apache.bintray.com/couchdb-deb $(lsb_release -sc) main"
  wget --quiet -O - https://couchdb.apache.org/repo/bintray-pubkey.asc | sudo apt-key add -
  sudo apt-get update
  sudo apt-get install couchdb
}

function install_yarn {
  wget --quiet -O - https://deb.nodesource.com/setup_10.x | sudo -E bash -
  sudo apt-get update
  sudo apt-get install -y nodejs
  sudo npm install -g yarn
}

function install_java {
  sudo apt-get install openjdk-8-jre-headless -y
}

function main {
  sudo add-apt-repository "deb http://archive.ubuntu.com/ubuntu $(lsb_release -sc) universe"
  sudo apt-get update -y
  sudo apt-get install -y make software-properties-common
  #sudo add-apt-repository -y ppa:ubuntugis/ubuntugis-unstable

  sudo apt-get install -y build-essential
  sudo apt-get install -y libxml2-dev
  sudo apt-get install -y libproj-dev
  sudo apt-get install -y libjson-c-dev
  sudo apt-get install -y xsltproc
  sudo apt-get install -y docbook-xsl
  sudo apt-get install -y docbook-mathml
  sudo apt-get install -y libgdal-dev
  sudo apt-get install -y libpq-dev

  sudo apt-get install python-pip -y
  pip install virtualenv==13.1.2

  echo -n "Would you like to install openjdk-8-jre? (y/n)? "
  read answer
  if echo "$answer" | grep -iq "^y" ;then
    echo Yes, installing Java 8
    install_java
  else
    echo Skipping Java installation
  fi

  echo -n "Would you like to install and configure postgres/postgis? (y/n)? "
  read answer
  if echo "$answer" | grep -iq "^y" ;then
    echo Yes, Installing postgis
    install_postgres
  else
    echo Skipping postgres/postgis installation
  fi

  echo -n "Would you like to install and configure couchdb? (y/n)? "
  read answer
  if echo "$answer" | grep -iq "^y" ;then
    echo Yes, Installing couchdb
    install_couchdb
  else
    echo Skipping couch installation
  fi

  echo -n "Would you like to install and nodejs/npm/and yarn (y/n)? "
  read answer
  if echo "$answer" | grep -iq "^y" ;then
    echo Yes, installing Node/Yarn
    install_yarn
  else
    echo Skipping node/npm/yarn installation
  fi
}

main
