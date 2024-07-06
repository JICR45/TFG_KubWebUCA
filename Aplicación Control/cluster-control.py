#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cluster Control Script for Kubernetes

Este script proporciona una serie de comandos para gestionar y controlar el clúster de Kubernetes.
Permite realizar operaciones como desplegar sitios, reiniciar contenedores, mostrar logs, y manejar backups, entre otros.

© 2024 - JICR 

"""

# Librerías necesarias
import sys
import logging
import os
import subprocess
import base64
import time
import json

from kubernetes import client, config

# Lista para almacenar los errores durante la ejecución del programa
errores = []

# Lista de nodos del clúster Kubernetes
listaNodosCluster = "          - kubwebnodo1\n          - kubwebnodo2\n          - kubwebnodo3"

# Definir las constantes
DIRECTORIO_SITIOS = "/opt/control/sitios"
DIRECTORIO_VOLUMENES = "/volumenes"

# Configuración básica de logging
logging.basicConfig(filename='/opt/control/logs/cluster-control.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

def printUso():
    # Función para mostrar por pantalla la sintaxis del programa
    uso = """\nUso: cluster-control.py COMANDO ...

COMANDO:

despliega <fichero JSON configuración>                              - Despliega el sitio
quita-despliegue-sitio <nombre>                                     - Elimina el despliegue del sitio
inicializa-sitio <nombre>                                           - Inicializa sitio Wordpress
estado-pods <nombre>                                                - Estado de los pods de un sitio
reinicia-contenedor <nombre> <"wordpress" | "bd">                   - Reinicia contenedor (sitio o bd)
muestra-logs <nombre> <"wordpress" | "bd">                          - Muestra logs (sitio o bd)
ejecuta-backup-bd <nombre>                                          - Ejecuta backup BD manual de la aplicacion
ejecuta-backup-wp <nombre>                                          - Ejecuta backup Wordpress manual de la aplicacion
listar-backup-bd <nombre>                                           - Lista los backup de base de datos disponibles
listar-backup-wp <nombre>                                           - Lista los backup de wordpress disponibles
restaurar-backup-bd <nombre> <fichero>                              - Restaura el backup de BD de <fichero> en el sitio <nombre>
restaurar-backup-wd <nombre> <fichero>                              - Restaura el backup de WP de <fichero> en el sitio <nombre>

"""
    # Escribe el texto de uso en la salida estándar de error
    sys.stderr.write(uso)

def crearDirectorio(ruta):
        # Función para crear un directorio dado        
        try:
            # Intenta crear el directorio con permisos 777
            os.makedirs(ruta, mode=0o777, exist_ok=True)
        except OSError as e:
            # Si ocurre un error, lo agrega a la lista de errores
            errores.append(f"No se ha podido crear el directorio {ruta}: {str(e)}")
            return False
        return True

def crearDirectoriosVolumenes(nombreSitio):
    # Función para crear todos los directorios necesarios para los despliegues

    # Intenta crear el directorio principal para el sitio
    if not crearDirectorio(f"{DIRECTORIO_VOLUMENES}/{nombreSitio}"):
        return 500, errores

    # Intenta crear el directorio para la base de datos
    if not crearDirectorio(f"{DIRECTORIO_VOLUMENES}/{nombreSitio}/bd"):
        return 500, errores

    # Intenta crear el directorio de datos para la base de datos
    if not crearDirectorio(f"{DIRECTORIO_VOLUMENES}/{nombreSitio}/bd/data"):
        return 500, errores

    # Intenta crear el directorio de backup para la base de dato
    if not crearDirectorio(f"{DIRECTORIO_VOLUMENES}/{nombreSitio}/bd/dump"):
        return 500, errores

    # Intenta crear el directorio para WordPress
    if not crearDirectorio(f"{DIRECTORIO_VOLUMENES}/{nombreSitio}/wp"):
        return 500, errores

    # Intenta crear el directorio de subidas para WordPress
    if not crearDirectorio(f"{DIRECTORIO_VOLUMENES}/{nombreSitio}/wp/uploads"):
        return 500, errores
    
    # Intenta crear el directorio de backup para WordPress
    if not crearDirectorio(f"{DIRECTORIO_VOLUMENES}/{nombreSitio}/wp/dump"):
        return 500, errores

    # Registra un mensaje de depuración indicando la finalización de la creación de directorios
    logger.debug(f"Finalización de la creación de directorios para {nombreSitio}")
    return 200, "Directorio(s) creado(s) exitosamente"

def crearNamespace(nombreSitio):
    # Función para crear un namespace

    # Verifica si existe el namespace
    existeNamespace = False
    comando = ["kubectl", "get", "namespace", nombreSitio]
    proceso = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proceso.communicate()
    
    # Verifica la salida para determinar si el namespace está activo
    for linea in stdout.decode().splitlines():
        logger.debug(f"Linea: {linea}\n")
        if f"{nombreSitio}   Active" in linea:
            existeNamespace = True
    
    # Si el namespace no existe, intenta crearlo
    if not existeNamespace:
        creadoNamespace = False
        comando = ["kubectl", "create", "namespace", nombreSitio]
        proceso = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proceso.communicate()
        
        # Verifica la salida para determinar si el namespace fue creado
        for linea in stdout.decode().splitlines():
            if f"namespace/{nombreSitio} created" in linea:
                creadoNamespace = True
        
        if not creadoNamespace:
            errores.append(f"No se ha podido crear el namespace {nombreSitio}")
            return 500, errores
        else:
            logger.debug(f"Namespace creado para {nombreSitio}")
            return 200, "Namespace creado exitosamente"
    else:
        return 200, "Namespace ya existe"
       
def verificaSecretoRepositorioExiste(nombreSitio):
    # Función para verificar si existe el secreto en el despliegue para acceder al repositorio Nexus

    existeSecreto = False
    try:
        # Ejecuta el comando kubectl para obtener el secreto
        output = subprocess.check_output(["kubectl", "get", "secret", "registry-nexusimgrepo", "-n", nombreSitio], stderr=subprocess.STDOUT)

        # Verifica la salida para determinar si el secreto existe
        for line in output.splitlines():
            line = line.decode("utf-8").strip()
            logger.debug(f"Linea: {line}")
            if "registry-nexusimgrepo" in line and "kubernetes.io/dockerconfigjson" in line:
                existeSecreto = True
                break
    except subprocess.CalledProcessError as e:
        logger.error(f"No se pudo obtener el secreto: {e.output.decode('utf-8').strip()}")
    return existeSecreto

def crearSecretoRepo(nombreSitio):
    # Función para crear el secreto en el despliegue para acceder al repositorio Nexus
    creadoSecreto = False
    try:
        # Comando kubectl para crear el secreto en el despliegue
        output = subprocess.check_output(["kubectl", "create", "secret", "docker-registry", "registry-nexusimgrepo", "--docker-server=nexusimgrepo.uca.es", "--docker-username=user", "--docker-password=password", "--docker-email=kubweb@uca.es", "-n", nombreSitio], stderr=subprocess.STDOUT)
        
        # Verifica la salida para determinar si el secreto fue creado
        for line in output.splitlines():
            line = line.decode("utf-8").strip()
            logger.debug(f"Linea: {line}")
            if "secret/registry-nexusimgrepo" in line and "created" in line:
                creadoSecreto = True
                break
    except subprocess.CalledProcessError as e:
        logger.error(f"No se pudo crear el secreto: {e.output.decode('utf-8').strip()}")
    return creadoSecreto

def crearSecretoRepositorio(nombreSitio): 
    # Función para verificar que un determinado secreto existe en el despliegue y, si no existe, crearlo   
    try:
        # Verificamos existencia del secreto
        if verificaSecretoRepositorioExiste(nombreSitio):
            logger.debug(f"Secreto de repositorio para {nombreSitio} ya existe")
            return 200, "Secreto de repositorio ya existe"
        else:
            # Creamos secreto si no existe
            if crearSecretoRepo(nombreSitio):
                logger.debug(f"Secreto de repositorio creado para {nombreSitio}")
                return 200, "Secreto creado exitosamente"
    except Exception as e:
        errores.append(f"Error al crear el secreto de acceso al repositorio de la aplicación {nombreSitio}: {str(e)}")
        logger.error(f"Ocurrió un error al crear el secreto al repositorio de la aplicación: {str(e)}")
        return 500, errores

def verificaSecretoOpaqueExiste(nombreSitio, clave):
    # Función para verificar si existe un determinado secreto del tipo Opaque en el despliegue
    existeSecreto = False
    try:
        # Intentamos obtener secreto con kubectl
        output = subprocess.check_output(["kubectl", "get", "secret", clave, "-n", nombreSitio], stderr=subprocess.STDOUT)
        
        # Verifica la salida para determinar si el secreto existe
        for line in output.splitlines():
            line = line.decode("utf-8").strip()
            logger.debug(f"Linea: {line}")
            if clave in line and "Opaque" and "1" in line:
                existeSecreto = True
                break
    except subprocess.CalledProcessError as e:
        logger.error(f"No se pudo obtener el secreto: {e.output.decode('utf-8').strip()}")
    return existeSecreto

def crearSecretoOpaque(nombreSitio, clave, password):
    # Función para crear un determinado secreto de tipo Opaque en el despliegue
    try:
        # Comprobamos si no existe el secreto para la BD MySQL en el despliegue
        if not verificaSecretoOpaqueExiste(nombreSitio, "mysql-bd-secret-config"):
            comando = f"echo '---\napiVersion: v1\nkind: Secret\nmetadata:\n   name: {clave}\n   namespace: {nombreSitio}\ntype: Opaque\ndata:\n   password: {password}\n' | kubectl apply -f -"
            output = subprocess.check_output(comando, shell=True, stderr=subprocess.STDOUT)

            # Verifica la salida para determinar si el secreto fue creado
            for line in output.splitlines():
                line = line.decode("utf-8").strip()
                logger.debug(f"Linea: {line}")
                if clave in line and "created" in line:
                    return 200, f"Secreto {clave} creado exitosamente"
                else:
                    return 200, f"Secreto {clave} ya existe"                    
        else:
            return 200, f"Secreto {clave} ya existe"
                    
    except subprocess.CalledProcessError as e:
        logger.error(f"No se pudo crear el secreto: {e.output.decode('utf-8').strip()}")
        return 500, errores    

def crearDeploymentBD(nombreSitio, version, passwordBD):
    # Función que genera el fichero YAML de despliegue para la base de datos MySQL

    deployBdContent = f"""apiVersion: v1
kind: Namespace
metadata:
  name: {nombreSitio}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: {nombreSitio}-bd-data-pv
  namespace: {nombreSitio}
spec:
  capacity:
    storage: 1Gi
  volumeMode: Filesystem
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Delete
  storageClassName: local-storage
  local:
    path: /volumenes/{nombreSitio}/bd/data
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
{listaNodosCluster}
---   
apiVersion: v1
kind: PersistentVolume
metadata:
  name: {nombreSitio}-bd-dump-pv
  namespace: {nombreSitio}
spec:
  capacity:
    storage: 5Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Delete
  storageClassName: local-storage
  local:
    path: /volumenes/{nombreSitio}/bd/dump
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
{listaNodosCluster}
---
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: bd-data-pvc
  namespace: {nombreSitio}  
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-storage
  resources:
    requests:
      storage: 1Gi
  volumeName: {nombreSitio}-bd-data-pv
---
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: bd-dump-pvc
  namespace: {nombreSitio}  
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-storage
  resources:
    requests:
      storage: 5Gi
  volumeName: {nombreSitio}-bd-dump-pv  
---
apiVersion: v1
kind: Secret
metadata:
   name: mysql-bd-secret-config
   namespace: {nombreSitio}
type: Opaque
data:
   password: {passwordBD}
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: mysql-opt-scripts
  namespace: {nombreSitio}
data:
  check_mysql.sh: |
        #!/bin/bash

        ## Script comprobación BD Wordpress está levantada

        mysql -u$MYSQL_USER -p$MYSQL_PASSWORD -e "USE $MYSQL_DATABASE;"
    
  backup_database.sh: |
        #!/bin/bash
        set -e

        dt=$(date '+%d/%m/%Y %H:%M:%S');
        fileDt=$(date '+%Y%m%d%H%M%S');
        backUpFileName="{nombreSitio}-$MYSQL_DATABASE-DB-$fileDt.gz"
        backUpFilePath="/dump/$backUpFileName"

        echo "$dt - Comienza copia BD {nombreSitio} en fichero: $backUpFilePath";
        echo "$dt - Ejecutando mysqldump | gzip > $backUpFilePath"

        mysqldump -uroot -p$MYSQL_ROOT_PASSWORD $MYSQL_DATABASE | gzip > $backUpFilePath

        if [ $? -ne 0 ]; then
          rm $backUpFilePath
          echo "No se puede realizar copia. Compruebe los parámetros de conexión a la BD"
          exit 1
        fi

        echo "$dt - Copia BD de {nombreSitio} completada en fichero: $backUpFilePath"; 
          
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {nombreSitio}-bd
  namespace: {nombreSitio}  
spec:
  replicas: 1
  revisionHistoryLimit: 0
  selector:
    matchLabels:
      tier: mysql
  template:
    metadata:
      labels:
        app: {nombreSitio}
        tier: mysql 
    spec:
      imagePullSecrets:
        - name: registry-nexusimgrepo
      containers:
        - name: mysql
          image: mysql:8.0
          imagePullPolicy: Always
          securityContext:
            allowPrivilegeEscalation: true
          ports:
            - containerPort: 3306 
          env:
            - name: MYSQL_USER
              value: wordpress
            - name: MYSQL_DATABASE
              value: wordpress
            - name: MYSQL_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: mysql-bd-secret-config
                  key: password
            - name: MYSQL_ROOT_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: mysql-bd-secret-config
                  key: password                     
          volumeMounts:             
            - mountPath: /var/lib/mysql
              name: mysql-persistent-storage             
            - mountPath: /dump
              name: volumen-mysql-dump
            - mountPath: /opt/scripts 
              name: mysql-opt-scripts-vol
          readinessProbe:
            exec:              
              command: ["/bin/bash", "/opt/scripts/check_mysql.sh"]
            initialDelaySeconds: 60
            periodSeconds: 10
            failureThreshold: 3              
      volumes:
        - name: mysql-persistent-storage
          persistentVolumeClaim:
            claimName: bd-data-pvc
        - name: volumen-mysql-dump
          persistentVolumeClaim:
            claimName: bd-dump-pvc
        - name: mysql-opt-scripts-vol
          configMap:
            name: mysql-opt-scripts
---
apiVersion: v1
kind: Service
metadata:
  name: {nombreSitio}-mysql-service
  namespace: {nombreSitio}
spec:
  ports:
  - port: 3306    
  selector:
    app: {nombreSitio}
    tier: mysql
  clusterIP: None 
"""
# Volcamos el texto en un fichero en la ubicación correspondiente
    try:
        with open(f"{DIRECTORIO_SITIOS}/{nombreSitio}/{nombreSitio}-bd-{version}.yaml", "w") as file:
            # Escribe el contenido en el archivo
            file.write(deployBdContent)
            logger.debug(f"Fichero de despliegue de BD creado para {nombreSitio}")
            return 200, "Fichero de despliegue de BD creado exitosamente"
    except Exception as e:
        errores.append(f"Error al crear el fichero de despliegue de BD de la aplicación {nombreSitio}: {str(e)}")
        logger.error(f"Ocurrió un error al Fichero de despliegue de BD de la aplicación: {str(e)}")
        return 500, errores

def crearDeploymentWP(nombreSitio, version, passWP, passAdminWP, mailUserWP, tituloSitio1, tituloSitio2, tipoEntidad):
    # Función que genera el fichero YAML de despliegue para la base de datos MySQL

  deployWpContent = f'''apiVersion: v1  
kind: Service
metadata:
  name: {nombreSitio}-wp-service
  namespace: {nombreSitio}
spec:
  ports:
    - port: 80
  selector:
    app: {nombreSitio}
    tier: frontend
  type: ClusterIP
---
apiVersion: v1
kind: Secret
metadata:
   name: wordpress-admin-secret-config
   namespace: {nombreSitio}
type: Opaque
data:
   password: {passWP}
---
apiVersion: v1
kind: Secret
metadata:
   name: wordpress-user-secret-config
   namespace: {nombreSitio}
type: Opaque
data:
   password: {passAdminWP}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: {nombreSitio}-wp-data-pv
  namespace: {nombreSitio}
spec:
  capacity:
    storage: 20Gi
  volumeMode: Filesystem
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Delete
  storageClassName: local-storage
  local:
    path: /volumenes/{nombreSitio}/wp/uploads
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
{listaNodosCluster}
---
apiVersion: v1
kind: PersistentVolume
metadata:
  name: {nombreSitio}-wp-dump-pv
  namespace: {nombreSitio}
spec:
  capacity:
    storage: 5Gi
  volumeMode: Filesystem
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Delete
  storageClassName: local-storage
  local:
    path: /volumenes/{nombreSitio}/wp/dump
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
{listaNodosCluster}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: wp-data-pvc
  namespace: {nombreSitio}
  labels:
    app: {nombreSitio}
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-storage
  resources:
    requests:
      storage: 20Gi
  volumeName: {nombreSitio}-wp-data-pv
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: wp-dump-pvc
  namespace: {nombreSitio}
  labels:
    app: {nombreSitio}
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-storage
  resources:
    requests:
      storage: 5Gi
  volumeName: {nombreSitio}-wp-dump-pv
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: wordpress-opt-scripts
  namespace: {nombreSitio}
data:
  wordpress-wp-cli-init.sh: |
        #!/bin/bash

        ## Script inicialización de sitio

        echo "Iniciando configuración inicial"
        sudo -E -u www-data wp core install --url=$WORDPRESS_SITE_URL --title=$WORDPRESS_SITE_NAME --admin_user=$WORDPRESS_ADMIN_USER --admin_password=$WORDPRESS_ADMIN_PASSWORD --admin_email=$WORDPRESS_ADMIN_MAIL --skip-email

        echo "Activamos Tema UCA"
        sudo -E -u www-data wp theme activate theme_main_uca

        echo "Creamos configuraciones personalizadas UCA"
        sudo -E -u www-data wp option add "theme_uca_settings" --format=json < /opt/scripts/theme_uca_settings_default.json

  wordpress-wp-cli-gestor.sh: |
        #!/bin/bash

        ## Script creación rol y usuario Gestor

        echo "Creando rol Gestor"
        sudo -E -u www-data wp role create gestor 'Gestor' --clone=editor

        echo "Modificando permisos rol Gestor"
        sudo -E -u www-data wp cap add gestor create_users list_users edit_users delete_users promote_users
        sudo -E -u www-data wp cap add gestor activate_plugins
        sudo -E -u www-data wp cap add gestor manage_options
        sudo -E -u www-data wp cap add gestor edit_theme_options
        sudo -E -u www-data wp cap add gestor wpml_manage_wp_menus_sync

        echo "Creando usuario Gestor"
        sudo -E -u www-data wp user create $WORDPRESS_USER $WORDPRESS_USER_MAIL --role=gestor --user_pass=$WORDPRESS_PASSWORD
  
  theme_uca_settings_default.json: |
      {{"theme_uca_fTituloLinea1":"{tituloSitio1}",
      "theme_uca_fTituloLinea2":"{tituloSitio2}",
      "theme_uca_fDescripcion":"",
      "theme_uca_fPresentacion":"uca_general",
      "theme_uca_fTipoEntidad":"{tipoEntidad}",
      "theme_uca_fCategoriaEnt":"uca_cat_default",
      "theme_uca_fPropiedadAnalytics":"UA-80714150-10",
      "theme_uca_fBuscadorAvanzado":"1",
      "theme_uca_fSavedData":"YES",
      "theme_uca_fCodPersonal":"",
      "theme_uca_fCodPersonal_aux":"",
      "theme_uca_fPersonalDefaultSort":"name::Nombre",
      "theme_uca_fMenuResponsables":"1",
      "theme_uca_fMenuPersonal":"1",
      "theme_uca_fMail":"",
      "theme_uca_fTlfno":"555 444 333",
      "theme_uca_fFax":"555 444 333",
      "theme_uca_fPostal":"Avda. Universidad de C\u00e1diz, n\u00ba 10, 11519 Campus Universitario de Puerto Real",
      "theme_uca_fContactForm":"",
      "theme_uca_fMapaLatitud":"36.52988",
      "theme_uca_fMapaLongitud":"-6.21177",
      "theme_uca_fFacebook":"https:\/\/www.facebook.com\/universidaddecadiz",
      "theme_uca_fTwitter":"https:\/\/twitter.com\/univcadiz",
      "theme_uca_fRss":"https:\/\/www.uca.es\/es\/rss",
      "theme_uca_fYoutube":"https:\/\/www.youtube.com\/videosUCA",
      "theme_uca_fInstagram":"https:\/\/www.instagram.com\/univcadiz\/",
      "theme_uca_fFlickr":"https:\/\/www.flickr.com\/photos\/147802205@N03\/albums",
      "theme_uca_fVk":""
      }}

  backup_uploads.sh: |
        #!/bin/bash
        set -e

        dt=$(date '+%d/%m/%Y %H:%M:%S');
        fileDt=$(date '+%Y%m%d%H%M%S');
        backUpFileName="{nombreSitio}-UPLOADS-WP-$fileDt.tgz"
        backUpFilePath="/dump/$backUpFileName"

        echo "$dt - Comienza copia Uploads {nombreSitio} en fichero: $backUpFilePath";
        echo "$dt - Ejecutando tar > $backUpFilePath"

        cd /var/www/html/wp-content/uploads/

        tar cvzf $backUpFilePath .

        if [ $? -ne 0 ]; then
          rm $backUpFilePath
          echo "No se puede realizar copia."
          exit 1
        fi

        echo "$dt - Copia Uploads de {nombreSitio} completada en fichero: $backUpFilePath"; 
          
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {nombreSitio}-wordpress
  namespace: {nombreSitio} 
spec:
  selector:
    matchLabels:      
      tier: frontend
  strategy:
    type: Recreate
  template:
    metadata:
      labels:
        app: {nombreSitio}        
        tier: frontend
    spec:
      imagePullSecrets:
        - name: registry-nexusimgrepo
      containers:
      - image: nexusimgrepo.uca.es/uca-wordpress/uca_wordpress:0.1 #wordpress:6.5-apache
        imagePullPolicy: Always
        securityContext:
          allowPrivilegeEscalation: true
        name: wordpress
        env:
          - name: WORDPRESS_SITE_URL
            value: {nombreSitio}.uca.es
            #value: kubwebpool001.uca.es
          - name: WORDPRESS_SITE_NAME
            value: Prueba
          - name: WORDPRESS_ADMIN_USER
            value: aducawp
          - name: WORDPRESS_ADMIN_PASSWORD
            valueFrom:
              secretKeyRef:
                name: wordpress-admin-secret-config
                key: password
          - name: WORDPRESS_ADMIN_MAIL
            value: web.ai@uca.es
          - name: WORDPRESS_USER
            value: gestor
          - name: WORDPRESS_PASSWORD
            valueFrom:
              secretKeyRef:
                name: wordpress-user-secret-config
                key: password
          - name: WORDPRESS_USER_MAIL
            value: {mailUserWP}
          - name: WORDPRESS_DB_HOST
            value: {nombreSitio}-mysql-service
          - name: WORDPRESS_DB_PASSWORD
            valueFrom:
              secretKeyRef:
                name: mysql-bd-secret-config
                key: password
          - name: WORDPRESS_DB_USER
            value: wordpress
        ports:
          - containerPort: 80
            name: wordpress
        volumeMounts:
          - name: wordpress-persistent-storage
            mountPath: /var/www/html/wp-content/uploads
          - name: wordpress-opt-scripts-vol
            mountPath: /opt/scripts 
          - name: volumen-wordpress-dump
            mountPath: /dump
                     
      volumes:
        - name: wordpress-persistent-storage
          persistentVolumeClaim:
            claimName: wp-data-pvc
        - name: wordpress-opt-scripts-vol
          configMap:
            name: wordpress-opt-scripts
        - name: volumen-wordpress-dump
          persistentVolumeClaim:
            claimName: wp-dump-pvc
  '''

  # Volcamos el texto en un fichero en la ubicación correspondiente
  try:
    with open(f"{DIRECTORIO_SITIOS}/{nombreSitio}/{nombreSitio}-wp-{version}.yaml", "w") as file:
            # Escribe el contenido en el archivo
            file.write(deployWpContent)
            logger.debug(f"Fichero de despliegue de WordPress creado para {nombreSitio}")
            return 200, "Fichero de despliegue de WordPress creado exitosamente"
  except Exception as e:
        errores.append(f"Error al crear el fichero de despliegue de WordPress de la aplicación {nombreSitio}: {str(e)}")
        logger.error(f"Ocurrió un error al Fichero de despliegue de WordPress de la aplicación: {str(e)}")
        return 500, errores

def crearDeploymentIngress(nombreSitio):
  # Función que genera el fichero YAML de despliegue del ingress
    
  # Creamos el alias que daremos de alta en el DNS
  nombreHost = f"{nombreSitio}.uca.es"  
  
  # Contenido del fichero de despliegue YAML del ingress
  deployIngressContent = f"""
  apiVersion: networking.k8s.io/v1
  kind: Ingress
  metadata:
    name: {nombreSitio}-ingress
    namespace: {nombreSitio}
  spec:   
    rules:
      - host: {nombreHost}
        http:
          paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {nombreSitio}-wp-service 
                port:
                  number: 80
  """
  # Volcamos el texto en un fichero en la ubicación correspondiente
  try:
      with open(f"{DIRECTORIO_SITIOS}/{nombreSitio}/{nombreSitio}-ingress.yaml", "w") as file:
          # Escribe el contenido en el archivo
          file.write(deployIngressContent)
          logger.debug(f"Fichero de despliegue de Ingress creado para {nombreSitio}")
          return 200, "Fichero de despliegue de Ingress creado exitosamente"
  except Exception as e:
      errores.append(f"Error al crear el fichero de despliegue de Ingress de la aplicación {nombreSitio}: {str(e)}")
      logger.error(f"Ocurrió un error al Fichero de despliegue de Ingress de la aplicación: {str(e)}")
      return 500, errores 

def despliegaYAML(nombreSitio, ficheroYAML):
    # Función que despliega en el cluster un fichero YAML dado en un determinado namespace

    # Comando para despplegar el fichero YAML
    comando = [
    "kubectl", "apply", 
    "-f", f"{ficheroYAML}", 
    "-n", nombreSitio
    ]

    errorDespliega = False
    changedAlgo = False

    logger.debug(f"kubectl apply -f {ficheroYAML} -n {nombreSitio}\n")

    try:
        # Ejecutamos el comando
        proceso = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proceso.communicate()

        # Procesamos salida del comando
        for linea in stdout.decode().splitlines():
            logger.debug(f"kubectl apply -{linea}\n")
            if " configured" in linea or " created" in linea:
                changedAlgo = True
            elif " unchanged" in linea:
                continue
            elif "invalid" in linea or "error" in linea:
                errores.append(f"Error en kubectl apply: {linea}")
                errorDespliega = True            

        # Procesamos si hay algún error
        for linea in stderr.decode().splitlines():
            logger.debug(f"Error en kubectl apply: -{linea}\n")
            if "error" in linea:
                errores.append(f"Error en kubectl apply: {linea}")
                errorDespliega = True

    except Exception as e:
        logger.error(f"Ocurrió una excepción ejecutando kubectl: {e}")
        errores.append(f"Ocurrió una excepción ejecutando kubectl: {str(e)}")
        errorDespliega = True

    # Manejo de resultados
    if errorDespliega:
        logger.error(f"Errores al aplicar kubectl: {errores}")
        return 500, errores
    else:
        if changedAlgo:
            logger.info(f"Algunos recursos fueron creados o configurados - {ficheroYAML}")
            return 200, f"Algunos recursos fueron creados o configurados - {ficheroYAML}"
        else:
            logger.info(f"No se realizaron cambios en el despliegue - {ficheroYAML}")
            return 200, f"No se realizaron cambios en el despliegue - {ficheroYAML}"

def despliegaSitio(ficheroConfig):
    # Función que a partir de un fichero JSON de configuración establece los parámetros del sitio a desplegar
    
    # Leemos fichero
    siteConfig = leeJSON(ficheroConfig) 

    # Establecemos parámetros
    nombreSitio = siteConfig['nombreSitio']
    version = siteConfig['version']
    passwordBaseDatos = siteConfig['passwordBD']
    passwordWP = siteConfig['passwordWP']
    passwordAdminWP = siteConfig['passwordAdminWP']
    mailUserWP = siteConfig['mailUserWP']
    tituloSitio1 = siteConfig['tituloSitio1']
    tituloSitio2 = siteConfig['tituloSitio2']
    tipoEntidad = siteConfig['tipoEntidad']
 
    logger.info(f"Comando: despliega {nombreSitio} {version}")
    logger.debug(f"Comando: despliega {nombreSitio} {version}")

    # Codificamos contraseñas 
    passwordBasedatosBase64 = base64.b64encode(passwordBaseDatos.encode()).decode()
    passwordWPBase64 = base64.b64encode(passwordWP.encode()).decode()
    passwordAdminWPBase64 = base64.b64encode(passwordAdminWP.encode()).decode()
    
    yaExiste = False
    creadoVolumenBd = False
    hayErrores = False
    
    # Creamos directorio en el servidor para dejar todos los ficheros de despliegue del sitio
    if not os.path.exists(f"{DIRECTORIO_SITIOS}/{nombreSitio}"):
        try:
            os.makedirs(f"{DIRECTORIO_SITIOS}/{nombreSitio}", mode=0o700)
        except OSError:
            errores.append(f"No se ha podido crear el directorio {DIRECTORIO_SITIOS}/{nombreSitio}")
            return 500, errores
    
    # Creamos namespace
    codigoResultado, resultado = crearNamespace(nombreSitio)
    if codigoResultado == 200:
        print(resultado)
    else:
        print("Error:", resultado)

    # Creamos directorios para los volúmentes persistentes 
    codigoResultado, resultado = crearDirectoriosVolumenes(nombreSitio)
    if codigoResultado == 200:
        print(resultado)
    else:
        hayErrores = True
        print("Error:", resultado)

    # Creamos credenciales para repositorio de imágenes
    codigoResultado, resultado = crearSecretoRepositorio(nombreSitio)
    if codigoResultado == 200:
        print(resultado)
    else:
        print("Error:", resultado)

    # Creamos fichero de despliegue de la base de datos
    codigoResultado, resultado = crearDeploymentBD(nombreSitio, version, passwordBasedatosBase64)
    if codigoResultado == 200:
        print(resultado)
    else:
        hayErrores = True
        print("Error:", resultado)
    
    # Creamos fichero de despliegue para el ingress
    codigoResultado, resultado = crearDeploymentIngress(nombreSitio)
    if codigoResultado == 200:
        print(resultado)
    else:
        hayErrores = True
        print("Error:", resultado)

    # Creamos fichero de despliegue para Wordpress
    codigoResultado, resultado = crearDeploymentWP(nombreSitio, version, passwordWPBase64, passwordAdminWPBase64, mailUserWP, tituloSitio1, tituloSitio2, tipoEntidad)
    if codigoResultado == 200:
        print(resultado)
    else:
        hayErrores = True
        print("Error:", resultado)
    
    # Desplegamos base de datos
    codigoResultado, resultado = despliegaYAML(nombreSitio, f"{DIRECTORIO_SITIOS}/{nombreSitio}/{nombreSitio}-bd-{version}.yaml")
    if codigoResultado == 200:
        print(resultado)
    else:
        hayErrores = True
        print("Error:", resultado)

    print("Esperando a la BD...")
    time.sleep(15) ### Esperamos a que se levante la BD correctamente    

    # Obtenemos la lista de pods, si encontramos el pod de base de datos continuamos el despliegue   
    resultado, pods = listaPods(nombreSitio)
    if resultado == 500:
      return 500, "No se pudo obtener la lista de pods"
    else:
      foundBD = False
      while not foundBD:
        for pod in pods:
          if 'bd' in pod:
              podBD = pod
              foundBD = True
              break          
        # Si no existe el pod de base de datos, salimos del proceso
        if not foundBD:       
            print("No se encuentra pod Base de Datos")
            return 500, "No se encuentra pod Base de Datos"  


    while True:
      # Comprobamos el estado del pod de base de datos
      condiciones = getPodStatus(nombreSitio, podBD)

      # Si está listo, desplegamos el Wordpress y el Ingress
      if isPodReady(condiciones):
        print(f"El pod {podBD} está listo. Desplegando el pod Wordpress...")
        codigoResultado, resultado = despliegaYAML(nombreSitio, f"{DIRECTORIO_SITIOS}/{nombreSitio}/{nombreSitio}-wp-{version}.yaml")
        if codigoResultado == 200:
          print(resultado)
        else:
          hayErrores = True
          print("Error:", resultado)
  
        codigoResultado, resultado = despliegaYAML(nombreSitio, f"{DIRECTORIO_SITIOS}/{nombreSitio}/{nombreSitio}-ingress.yaml")
        if codigoResultado == 200:
          print(resultado)
        else:
          hayErrores = True
          print("Error:", resultado)        
        break
      
      # Si no está listo, seguimos esperando
      else:
        print(f"El pod {podBD} no está listo. Esperando...")
        time.sleep(10) 

    print("Esperando a WP...")
    time.sleep(15) ### Esperamos a que se levante Wordpress correctamente   
 
    # Comprobamos que existe el pod de Wordpress
    resultado, pods = listaPods(nombreSitio)
    if resultado == 500:
      return 500, "No se pudo obtener la lista de pods"
    else:
      foundWP = False
      while not foundWP:
        for pod in pods:
          if 'wordpress' in pod:
              podWP = pod
              foundWP = True
              break
        # Si no existe el pod de Wordpress, salimos del proceso  
        if not foundWP:       
            print("No se encuentra pod WordPress")
            return 500, "No se encuentra pod WordPress"

    while True:
        # Comprobamos que el pod de Wordpress se encuentre disponible para inicializar el sitio
        condiciones = getPodStatus(nombreSitio, podWP)
        if isPodReady(condiciones):
          print(f"El pod {podWP} está listo. Inicializando sitio Wordpress...")        
          codigoResultado, resultado = inicializaSitioWP(nombreSitio)
          if codigoResultado == 200:
            print(resultado)
          else:
            hayErrores = True
            print("Error:", resultado)
          break
        
        # Si no está listo, seguimos esperando
        else:
          print(f"El pod {podWP} no está listo. Esperando...")
          time.sleep(10)  
    
    # Devolvemos el resultado del despliegue
    if hayErrores:
        return 500, "Despliegue con errores"
    else:
        return 200, "Despliegue exitoso"

def eliminaDespliegueSitio(nombreSitio):    
  # Función para eliminar todos los objetos asociados un despliegue

  # Comandos a ejecutar para eliminar todos los objetos asociados un despliegue
  comandos = [
      f"kubectl delete deployments --all -n {nombreSitio}",
      f"kubectl delete services --all -n {nombreSitio}",
      f"kubectl delete pods --all -n {nombreSitio}",
      f"kubectl delete pvc bd-data-pvc -n {nombreSitio}",
      f"kubectl delete pvc wp-data-pvc -n {nombreSitio}",
      f"kubectl delete pvc bd-dump-pvc -n {nombreSitio}",
      f"kubectl delete pvc wp-dump-pvc -n {nombreSitio}",
      f"kubectl delete pv {nombreSitio}-wp-data-pv",
      f"kubectl delete pv {nombreSitio}-bd-data-pv",
      f"kubectl delete pv {nombreSitio}-bd-dump-pv",
      f"kubectl delete pv {nombreSitio}-wp-dump-pv",
      f"kubectl delete namespace {nombreSitio}"
  ]
    
  resultado = ""
  
  # Ejecutamos cada uno de los comandos y vamos almacenando el resultado
  for comando in comandos:
    try:
      proceso = subprocess.Popen(comando, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
      stdout, stderr = proceso.communicate()      
      for linea in stdout.splitlines():        
        resultado += linea + "\n"
      if proceso.returncode != 0:
        for linea in stderr.splitlines():
          resultado += f"Error: {linea}\n"
       
    except Exception as e:
       resultado += f"Error ejecutando el comando {comando}: {str(e)}\n"
       return 500, resultado
    
  return 200, resultado

def listaPods(nombreSitio):
  # Función para listar todos los pods asociados a un sitio

  # Configurar el cliente de la API de Kubernetes
  config.load_kube_config()
  v1 = client.CoreV1Api()

  # Obtener la lista de Pods en el namespace especificado
  try:
    listaPods = v1.list_namespaced_pod(namespace=nombreSitio)
    nombresPods = [pod.metadata.name for pod in listaPods.items]
    return 200, nombresPods
  except client.exceptions.ApiException as e:
    print(f"Error al obtener los Pods: {e}")
    return 500, []

def inicializaSitioWP(nombreSitio):
  # Función para incializar un sitio web 

  resultado, pods = listaPods(nombreSitio)

  # Obtenemos el nombre del pod de Wordpress 
  if resultado == 500:
      return 500, "No se pudo obtener la lista de pods"
  else:
    for pod in pods:
        if 'wordpress' in pod:
            podWP = pod
            break
    
    # Si está desplegado el pod, ejecutamos los comandos de inicialización del sitio  
    if podWP:    
      comando1 = f"kubectl exec --stdin {pod} -n {nombreSitio} -- bash /opt/scripts/wordpress-wp-cli-init.sh"
      comando2 = f"kubectl exec --stdin {pod} -n {nombreSitio} -- bash /opt/scripts/wordpress-wp-cli-gestor.sh"
     
      proceso1 = subprocess.run(comando1, shell=True, capture_output=True, text=True)
      proceso2 = subprocess.run(comando2, shell=True, capture_output=True, text=True)
      
      if proceso1.returncode != 0 or proceso2.returncode != 0:
          logger.error(f"Error: No se pudieron ejecutar los scripts de inicialización de sitio")
          return 500, "No se pudo inicializar sitio"
      else:
        logger.info(f"Comandos inicialización ejecutados: {comando1}, {comando2}")
        return 200, "Sitio Wordpress Inicializado"
    else:
        return 500, "No se encuentra pod Wordpress"
    
def getPodStatus(nombreSitio, nombrePod):
    # Función que nos devuelve una lista con los estados en los que está un pod

    # Configura la API de Kubernetes
    config.load_kube_config()
    v1 = client.CoreV1Api()

    # Obtiene el nombre del pod
    pod = v1.read_namespaced_pod(name=nombrePod, namespace=nombreSitio)

    # Devolvemos los estados del pod
    return pod.status.conditions

def isPodReady(conditions):
    # Función para comprobar si el pod se encuentra en estado 'Ready'
    for condition in conditions:
        if condition.type == "Ready" and condition.status == "True":
            return True
    return False
    
def leeJSON(fichero):
    # Función que lee un fichero JSON con la configuración de un sitio
    with open(fichero, 'r') as file:
      config = json.load(file)
    
    return config['website']

def reiniciaPod(nombreSitio, nombrePod):
    # Función que reinicia un pod dad

    resultado = 0

    # Log del comando que se va a ejecutar (para debug)
    print(f"kubectl delete pod {nombrePod} -n {nombreSitio}")

    try:
        # Ejecutar el comando kubectl
        proceso = subprocess.Popen(
            ["kubectl", "delete", "pod", nombrePod, "-n", nombreSitio],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = proceso.communicate()

        # Procesar la salida del comando
        salida = stdout.decode()
        if "deleted" in salida:  # Verifica que el pod se ha eliminado
            resultado = 1

    except Exception as e:
        print(f"Error al ejecutar el comando: {e}")

    return resultado    

def reiniciaContenedor(nombreSitio, contenedor):
  # Función que dado un sitio y la cadena BD o Wordpress ejecuta el reinicio del pod correspondiente
   
    # Obtenemos la lista de pods   
    resultado, pods = listaPods(nombreSitio)
    problemas = False

    # Recorremos la lista de pods y reiniciamos el que contenga la cadena dada
    if resultado:
        for pod in pods:
          if contenedor in pod:
              if reiniciaPod(nombreSitio, pod):
                logger.info(f"{contenedor} de {nombreSitio} inicializado correctamente")
                errores.append("Aplicación reiniciada correctamente")
              else:
                  errores.append(f"No se ha podido inicializar {contenedor} de {nombreSitio}")
                  logger.error(f"No se ha podido inicializar {contenedor} de {nombreSitio}")
                  problemas = True            
        if not problemas:      
          return 200, "Proceso de reinicio completado"
        else:
          return 500, "No se ha podido reiniciar contenedor"
    
    else: 
        return 500, "Reinicia Contenedor - No se puede obtener lista de pods" 

def muestraLogs(nombreSitio, contenedor):
    # Función que dado un sitio y la cadena BD o Wordpress nos muestra el log asociado por pantalla

    # Obtenemos la lista de pods
    resultado, pods = listaPods(nombreSitio)
      
    if resultado:
        # Recorremos la lista de pod 
        for pod in pods:           
          if contenedor in pod:                  
            try:
              # Ejecutar el comando kubectl              
              proceso = subprocess.Popen(
                ["kubectl", "logs", pod, "-n", nombreSitio],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
              )
              stdout, stderr = proceso.communicate()

              # Procesar la salida del comando
              for linea in stdout.decode().split('\n'):
                print(linea)            
                            
              logger.info(f"Log {contenedor} de {nombreSitio} mostrado correctamente")
              errores.append(f"Log {contenedor} de {nombreSitio} mostrado correctamente")

              return 200, f"Log {contenedor} de {nombreSitio} mostrado correctamente"
            except Exception as e:
              print(f"Error al ejecutar el comando: {e}")
              errores.append(f"No se ha podido mostrar log {contenedor} de {nombreSitio}")
              logger.error(f"No se ha podido mostrar log {contenedor} de {nombreSitio}") 
              return 500, f"No se ha podido mostrar log {contenedor} de {nombreSitio}"          
    else: 
      return 500, f"Logs {nombreSitio} - No se puede obtener lista de pods" 

def ejecutaBackup(nombreSitio, contenedor):
    # Función que dado un sitio y la cadena BD o Wordpress ejecuta una copia de seguridad de sus datos persistentes 

    # Obtenemos lista de pods
    resultado, pods = listaPods(nombreSitio)           

    # En función del contenido del parámetro 'contenedor' ejecutaremos un script u otro
    if resultado:
        for pod in pods:
            if contenedor in pod and "bd" in contenedor:
                comando =  f"kubectl exec --stdin {pod} -n {nombreSitio} -- /bin/bash /opt/scripts/backup_database.sh"     
            elif contenedor in pod and "wordpress" in contenedor:
                comando = f"kubectl exec --stdin {pod} -n {nombreSitio} -- /bin/bash /opt/scripts/backup_uploads.sh"                      
        
        # Ejecutar el comando kubectl   
        proceso = subprocess.run(comando, shell=True, capture_output=True, text=True)                     
        if proceso.returncode !=0:
          errores.append(f"No se ha podido realizar el backup de {contenedor} de {nombreSitio}")
          logger.error(f"No se ha podido realizar el backup de {contenedor} de {nombreSitio}")
          return 500, f"No se ha podido realizar el backup de {contenedor} de {nombreSitio}"
        else:                          
          logger.info(f"Backup de {contenedor} de {nombreSitio} realizada correctamente")
          errores.append(f"Backup de {contenedor} de {nombreSitio} realizada correctamente")
          return 200, f"Backup de {contenedor} de {nombreSitio} realizada correctamente"
         
    else: 
      return 500, f"Logs {nombreSitio} - No se puede obtener lista de pods"               

def listarBackup(nombreSitio, contenedor):
    # Función que dado un sitio y la cadena BD o Wordpress lista las copias de seguridad disponibles

    # Establecemos el directorio en función del contenido de 'contenedor'
    if "bd" in contenedor:
        directorio = f"{DIRECTORIO_VOLUMENES}/{nombreSitio}/bd/dump"
    elif "wordpress" in contenedor:
        directorio = f"{DIRECTORIO_VOLUMENES}/{nombreSitio}/wp/dump"
        
    try:
        # Almacenmos el contenido del directorio en una lista
        contenido = os.listdir(directorio)        
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")
        errores.append(f"No se ha podido listar el contenido del directorio {contenedor} de {nombreSitio}")
        logger.error(f"No se ha podido listar el contenido del directorio {contenedor} de {nombreSitio}")
        return 500, f"No se ha podido listar el contenido del directorio {contenedor} de {nombreSitio}"             

    if contenido:
        print(f"Contenido del directorio '{directorio}':")
        # Recorremos la lista de ficheros y la vamos mostrando por pantalla
        for item in contenido:
            print(item)
        logger.info(f"Listado del directorio {contenedor} de {nombreSitio} realizado correctamente")
        errores.append(f"Listado del directorio {contenedor} de {nombreSitio} realizado correctamente")
        return 200, f"Listado del directorio {contenedor} de {nombreSitio} realizado correctamente"
    else:
        print(f"El directorio '{directorio}' está vacío o no se pudo acceder.")
        errores.append(f"No se ha podido listar el contenido del directorio {contenedor} de {nombreSitio}")
        logger.error(f"No se ha podido listar el contenido del directorio {contenedor} de {nombreSitio}")
        return 500, f"No se ha podido listar el contenido del directorio {contenedor} de {nombreSitio}"
        
def restauraBackup(nombreSitio, contenedor, fichero):
    # Función que dado un sitio, la cadena BD o Wordpress y un nombre de fichero, restaura una copia de seguridad

    # Obtenemos listado de pods
    resultado, pods = listaPods(nombreSitio)           

    if resultado:
        # Recorremos lista de pods para obtener su nombre y generar el comando adecuado para la restauración
        for pod in pods:
            if contenedor in pod and "bd" in contenedor:
                comando = f"kubectl exec --stdin {pod} -n {nombreSitio} -- bash -c \"zcat /dump/{fichero} | mysql -u\$MYSQL_USER -p\$MYSQL_PASSWORD \$MYSQL_DATABASE\""
            elif contenedor in pod and "wordpress" in contenedor:
                comando = f"kubectl exec --stdin {pod} -n {nombreSitio} -- tar xvzf /dump/{fichero} -C /var/www/html/wp-content/uploads"

        # Ejecutar el comando kubectl   
        proceso = subprocess.run(comando, shell=True, capture_output=True, text=True)                     
        if proceso.returncode !=0:
          errores.append(f"No se ha podido restaurar el backup de {contenedor} de {nombreSitio}")
          logger.error(f"No se ha podido restaurar el backup de {contenedor} de {nombreSitio}")
          return 500, f"No se ha podido restaurar el backup de {contenedor} de {nombreSitio}"
        else:                          
          logger.info(f"Backup de {contenedor} de {nombreSitio} restaurado correctamente")
          errores.append(f"Backup de {contenedor} de {nombreSitio} restaurado correctamente")
          return 200, f"Backup de {contenedor} de {nombreSitio} restaurado correctamente"
         
    else: 
      return 500, f"Logs {nombreSitio} - No se puede obtener lista de pods"               

def main():
  # Obtener los argumentos de la línea de comandos
  args = sys.argv[1:]
  
  # Extraer la acción y los parámetros
  if not args:
      print("Error: No se recibieron argumentos.")
      printUso()
      sys.exit(1)
  else:
      accion = args[0]
      parametros = args[1:]
  
  # Despliega sitio
  if accion == "despliega":
      if len(parametros) != 1:
          print("Error: Se requiere como parámetro un fichero JSON de configuración.")
          printUso()
          sys.exit(1)
      
      ficheroConfig = parametros[0]   

      codigoResultado, resultado = despliegaSitio(ficheroConfig)
      print(resultado)      
  
  # Elimina despliegue
  elif accion == "quita-despliegue-sitio":
      if len(parametros) != 1:
          print("Error: Se requiere un parámetro: nombre de sitio.")
          printUso()
          sys.exit(1)
      
      nombreSitio = parametros[0]
      logger.info(f"Comando: Elimina despliegue {nombreSitio}")

      codigoResultado, resultado = eliminaDespliegueSitio(nombreSitio)
      if codigoResultado == 200:
          print(resultado)
      else:
          print(resultado)

  # Listado de pods de un sitio
  elif accion == "lista-pods":
      if len(parametros) != 1:
          print("Error: Se requiere un parámetro: nombre de sitio.")
          printUso()
          sys.exit(1)

      nombreSitio = parametros[0]
      logger.info(f"Comando: Lista pods {nombreSitio}")

      codigoResultado, resultado = listaPods(nombreSitio)
      if codigoResultado == 200:
          print(resultado)
      else:
          print(resultado)
  
  # Inicializa sitio web
  elif accion == "inicializa-sitio":
    if len(parametros) != 1:
        print("Error: Se requiere un parámetro: nombre de sitio.")
        printUso()
        sys.exit(1)
    nombreSitio = parametros[0]
    logger.info(f"Comando: Inicializa sitio WP {nombreSitio}")
    codigoResultado, resultado = inicializaSitioWP(nombreSitio)
    if codigoResultado == 200:
        print(resultado)
    else:
        print(resultado)

  # Devuelve estado de los pods de un sitio
  elif accion == "estado-pods":
    if len(parametros) != 1:
        print("Error: Se requiere un parámetro: nombre de sitio.")
        printUso()
        sys.exit(1)
    nombreSitio = parametros[0]
    logger.info(f"Comando: Estado pods {nombreSitio}")
    _,pods=listaPods(nombreSitio)    
    for pod in pods:
      print(pod)
      resultado = getPodStatus(nombreSitio, pod)
      print(resultado)

  # Reinicia un pod de un determinado sitio
  elif accion == "reinicia-contenedor":
    if len(parametros) != 2:
        print("Error: Se requieren dos parámetros: nombre de sitio y wordpress o bd.")
        printUso()
        sys.exit(1)
    
    nombreSitio, tipo = parametros

    logger.info(f"Comando: reinicia-contenedor {nombreSitio} {tipo}")
    codigoResultado, resultado = reiniciaContenedor(nombreSitio, tipo)
    if codigoResultado == 200:
        print(resultado)
    else:
        print(resultado)

  # Muestra los logs de un pod de un determinado sitio
  elif accion == "muestra-logs":
    if len(parametros) != 2:
        print("Error: Se requieren dos parámetros: nombre de sitio y wordpress o bd.")
        printUso()
        sys.exit(1)

    nombreSitio, tipo = parametros
    logger.info(f"Comando: muestra-logs {nombreSitio} {tipo}")
    codigoResultado, resultado = muestraLogs(nombreSitio, tipo)
    if codigoResultado == 200:
        print(resultado)
    else:
        print(resultado)  
  
  # Realiza una copia de seguridad de la base de datos de un determinado sitio
  elif accion == "ejecuta-backup-bd":
    if len(parametros) != 1:
        print("Error: Se requieren un parámetro: nombre de sitio")
        printUso()
        sys.exit(1)

    nombreSitio = parametros[0]
    logger.info(f"Comando: ejecuta-backup-bd {nombreSitio}")
    codigoResultado, resultado = ejecutaBackup(nombreSitio, "bd")
    if codigoResultado == 200:
        print(resultado)
    else:
        print(resultado) 

  # Realiza una copia de seguridad del Wordpress (carpeta UPLOADS) de un determinado sitio  
  elif accion == "ejecuta-backup-wp":
    if len(parametros) != 1:
        print("Error: Se requieren un parámetro: nombre de sitio")
        printUso()
        sys.exit(1)

    nombreSitio = parametros[0]
    logger.info(f"Comando: ejecuta-backup-wp {nombreSitio}")
    codigoResultado, resultado = ejecutaBackup(nombreSitio,"wordpress")
    if codigoResultado == 200:
        print(resultado)
    else:
        print(resultado)   

  # Lista las copias de seguridad de la base de datos de un determinado sitio
  elif accion == "listar-backup-bd":
    if len(parametros) != 1:
        print("Error: Se requieren un parámetro: nombre de sitio")
        printUso()
        sys.exit(1)

    nombreSitio = parametros[0]
    logger.info(f"Comando: listar-backup-bd {nombreSitio}")
    codigoResultado, resultado = listarBackup(nombreSitio,"bd")
    if codigoResultado == 200:
        print(resultado)
    else:
        print(resultado) 

  # Lista las copias de seguridad de Wordpress de un determinado sitio
  elif accion == "listar-backup-wp":
    if len(parametros) != 1:
        print("Error: Se requieren un parámetro: nombre de sitio")
        printUso()
        sys.exit(1)

    nombreSitio = parametros[0]
    logger.info(f"Comando: listar-backup-wp {nombreSitio}")
    codigoResultado, resultado = listarBackup(nombreSitio,"wordpress")
    if codigoResultado == 200:
        print(resultado)
    else:
        print(resultado) 

  # Resatura una copia de seguridad de la base de datos de un determinado sitio
  elif accion == "restaurar-backup-wp":
    if len(parametros) != 2:
        print("Error: Se requieren dos parámetros: nombre de sitio y fichero a restaurar")
        printUso()
        sys.exit(1)

    nombreSitio, fichero = parametros
    logger.info(f"Comando: restaurar-backup-wp {nombreSitio}")
    codigoResultado, resultado = restauraBackup(nombreSitio, "wordpress", fichero)
    if codigoResultado == 200:
        print(resultado)
    else:
        print(resultado) 

  # Resatura una copia de seguridad de Wordpress de un determinado sitio
  elif accion == "restaurar-backup-bd":
    if len(parametros) != 2:
        print("Error: Se requieren dos parámetros: nombre de sitio y fichero a restaurar")
        printUso()
        sys.exit(1)

    nombreSitio, fichero = parametros
    logger.info(f"Comando: restaurar-backup-bd {nombreSitio}")
    codigoResultado, resultado = restauraBackup(nombreSitio, "bd", fichero)
    if codigoResultado == 200:
        print(resultado)
    else:
        print(resultado) 

  else:
      printUso()
      sys.exit(1)

if __name__ == "__main__":
    main() 
