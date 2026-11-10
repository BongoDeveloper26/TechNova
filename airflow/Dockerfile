# Imagen de Airflow para TechNova: la oficial + las librerías que usa nuestro ETL
FROM apache/airflow:3.3.2-python3.12
 
# Se instala fijando la versión de Airflow para que pip no la cambie al resolver dependencias
COPY requirements-airflow.txt /tmp/requirements-airflow.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /tmp/requirements-airflow.txt
 
# Script de arranque. El sed quita los saltos de línea de Windows (\r\n -> \n):
# si el fichero se guardó en Windows, Linux no podría ejecutarlo
USER root
COPY arrancar.sh /opt/airflow/arrancar.sh
RUN sed -i 's/\r$//' /opt/airflow/arrancar.sh && chmod 755 /opt/airflow/arrancar.sh
USER airflow
 