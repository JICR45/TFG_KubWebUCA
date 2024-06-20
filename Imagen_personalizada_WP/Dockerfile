FROM wordpress:6.5-apache

# Definir variables de entorno
WORKDIR /var/www/html

# Instalar dependencias
RUN apt-get update && apt-get install -y curl wget unzip sudo

# Instalamos wp-cli
RUN curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
RUN chmod +x wp-cli.phar
RUN mv wp-cli.phar /usr/local/bin/wp

# Descargar el tema personalizado
USER www-data
COPY theme_main_uca.zip /tmp

# Extraer el tema personalizado
RUN unzip /tmp/theme_main_uca.zip -d /var/www/html/wp-content/themes/

USER root
