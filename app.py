from flask import Flask, render_template, request, jsonify, Response
from flask_httpauth import HTTPBasicAuth
import paramiko
import subprocess
import re

app = Flask(__name__)
auth = HTTPBasicAuth()

# Variables para mantener la sesión SSH activa
ssh_client = None
ssh_transport = None

# Diccionario con los usuarios y contraseñas
users = {
    "admin": "admin"
}

# Función para verificar el nombre de usuario y la contraseña
@auth.verify_password
def verify_password(username, password):
    if username in users and users[username] == password:
        return username

@app.route('/')
@auth.login_required
def index():
    return render_template('index.html')

@app.route('/configurar_ip')
def configurar_ip_page():
    return render_template('configurar_ip.html')

@app.route('/configurar', methods=['POST'])
def configurar_ip():
    ip = request.form['ip-address']
    subnet = request.form['subnet-mask']
    gateway = request.form['gateway']
    dns1 = request.form['dns1']
    dns2 = request.form['dns2']

    netplan_file = "/etc/netplan/50-cloud-init.yaml"

    try:
        # Crear o sobreescribir el archivo de configuración de red
        with open(netplan_file, 'w') as f:
            f.write(f"""
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: false
      addresses:
        - {ip}/{subnet}
      gateway4: {gateway}
      nameservers:
        addresses:
          - {dns1}
          - {dns2}
""")

        # Aplicar los cambios de red
        subprocess.run(["sudo", "netplan", "apply"], check=True)

        return jsonify({"success": True, "message": "IP configurada correctamente"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/gestion_usuarios')
def gestion_usuarios_page():
    return render_template('gestion_usuarios.html')

# Nueva ruta para el formulario de creación de usuario
@app.route('/crear_usuario')
def crear_usuario_page():
    return render_template('crear_usuario.html')

# Ruta para manejar la creación de un nuevo usuario
@app.route('/crear_usuario', methods=['POST'])
def crear_usuario():
    username = request.form['nombre']
    home = request.form['home']
    password = request.form['password']

    try:
        # Ejecutar el comando para crear un usuario en Linux usando 'useradd'
        subprocess.run(['sudo', 'useradd', '-m', '-d', home, username], check=True)
        
        # Asignar la contraseña al usuario
        subprocess.run(['sudo', 'bash', '-c', f"echo '{username}:{password}' | chpasswd"], check=True)

        return jsonify({"success": True, "message": f"Usuario {username} creado correctamente"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/eliminar_usuario', methods=['POST'])
def eliminar_usuario():
    try:
        # Obtener el nombre del usuario a eliminar
        username = request.form['nombre']

        # Ejecutar el comando para eliminar al usuario
        subprocess.run(['sudo', 'userdel', '-r', username], check=True)

        return jsonify({"success": True, "message": f"Usuario {username} eliminado correctamente"}), 200
    except KeyError as e:
        return jsonify({"success": False, "message": f"Falta el campo: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route('/crear_grupo', methods=['POST'])
def crear_grupo():
    try:
        # Obtener el nombre del grupo desde el formulario
        groupname = request.form['nombre_grupo']

        # Ejecutar el comando para crear el grupo
        subprocess.run(['sudo', 'groupadd', groupname], check=True)

        return jsonify({"success": True, "message": f"Grupo {groupname} creado correctamente"}), 200
    except KeyError as e:
        return jsonify({"success": False, "message": f"Falta el campo: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/ver_usuarios', methods=['GET'])
def ver_usuarios():
    try:
        # Ejecutar el comando para obtener la lista de usuarios
        result = subprocess.run(['getent', 'passwd'], capture_output=True, text=True)

        # Procesar la salida para extraer los nombres de usuario
        users = []
        for line in result.stdout.splitlines():
            user_data = line.split(':')
            username = user_data[0]
            users.append(username)

        # Renderizar la plantilla HTML con la lista de usuarios
        return render_template('ver_usuarios.html', usuarios=users)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# Ruta para ver grupos
@app.route('/ver_grupos', methods=['GET'])
def ver_grupos():
    try:
        result = subprocess.run(['getent', 'group'], capture_output=True, text=True)

        grupos = []
        for line in result.stdout.splitlines():
            group_data = line.split(':')
            groupname = group_data[0]
            grupos.append(groupname)

        return render_template('ver_grupos.html', grupos=grupos)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    
def convert_to_bytes(value):
    """Convierte tamaños de disco a bytes y maneja comas como separadores decimales"""
    try:
        # Reemplazar la coma por un punto para asegurar el formato decimal correcto
        value = value.replace(',', '.')
        if value.endswith('G'):
            return float(value[:-1]) * 1024 ** 3  # G -> bytes
        elif value.endswith('M'):
            return float(value[:-1]) * 1024 ** 2  # M -> bytes
        elif value.endswith('K'):
            return float(value[:-1]) * 1024  # K -> bytes
        elif value.endswith('T'):
            return float(value[:-1]) * 1024 ** 4  # T -> bytes
        else:
            return float(value)  # Sin unidad, convertir directamente
    except ValueError:
        raise ValueError(f"No se pudo convertir el valor a float: {value}")

@app.route('/almacenamiento', methods=['GET', 'POST'])
def almacenamiento():
    if request.method == 'GET':
        # Ejecutamos lsblk para obtener los discos (solo discos, sin particiones)
        result = subprocess.run(['lsblk', '-o', 'NAME,SIZE,TYPE,MOUNTPOINT'],
                                  capture_output=True, text=True)
        discos = []
        for line in result.stdout.splitlines():
            # Filtramos las líneas que correspondan a discos (TYPE contiene "disk")
            if 'disk' in line:
                parts = line.split()
                if len(parts) >= 2:
                    nombre = parts[0]
                    # Convertimos el tamaño a bytes (para uso interno; en el template podemos formatearlo)
                    tamaño = convert_to_bytes(parts[1])
                    discos.append({'nombre': nombre, 'tamaño': tamaño})
        
        # Obtenemos el uso de los discos con df -h
        result_uso = subprocess.run(['df', '-h'], capture_output=True, text=True)
        discos_uso = []
        # Ignoramos la cabecera (primera línea)
        for line in result_uso.stdout.splitlines()[1:]:
            parts = line.split()
            # Verificamos que se trate de una partición de disco (por ejemplo, /dev/sda1)
            if parts[0].startswith('/dev/sd'):
                # Extraemos el nombre del disco principal (eliminando números finales)
                nombre = re.sub(r'\d+$', '', parts[0].replace('/dev/', ''))
                # El porcentaje de uso se encuentra normalmente en la 5ª columna (Use%)
                uso_str = parts[4].replace('%', '')
                try:
                    uso_float = float(uso_str)
                except ValueError:
                    uso_float = 0
                discos_uso.append({'nombre': nombre, 'usado': uso_float})
        
        # Unir la información de uso a cada disco
        for disco in discos:
            # Buscamos en discos_uso un registro con el mismo nombre
            for uso in discos_uso:
                if disco['nombre'] == uso['nombre']:
                    disco['usado'] = uso['usado']
                    break
            else:
                disco['usado'] = 0  # Si no se encontró, asumimos 0%
        
        return render_template('almacenamiento.html', discos=discos)

    if request.method == 'POST':
        try:
            discos_seleccionados = request.form.getlist('discos')
            tipo_raid = request.form['raid']

            # Comando de ejemplo para crear RAID usando mdadm:
            comando = ['mdadm', '--create', '--verbose', '/dev/md0', '--level=' + tipo_raid]
            comando += ['--raid-devices=' + str(len(discos_seleccionados))] + discos_seleccionados

            result = subprocess.run(comando, capture_output=True, text=True)
            if result.returncode == 0:
                return jsonify({"success": True, "message": "RAID creado con éxito"})
            else:
                return jsonify({"success": False, "message": result.stderr}), 500

        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500


@app.route('/ssh_terminal')
def ssh_terminal_page():
    return render_template('ssh_terminal.html')

@app.route('/ssh_login', methods=['POST'])
def ssh_login():
    global ssh_client, ssh_transport

    hostname = request.form['hostname']
    username = request.form['username']
    password = request.form['password']

    try:
        # Crear una nueva instancia SSHClient
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(hostname, username=username, password=password)

        # Mantener la sesión abierta
        ssh_transport = ssh_client.get_transport()

        return jsonify({"success": True, "message": "Sesión SSH iniciada correctamente"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/run_command', methods=['POST'])
def run_command():
    global ssh_client

    if not ssh_client:
        return jsonify({"success": False, "message": "No hay sesión SSH activa."}), 400

    command = request.form['command']

    try:
        stdin, stdout, stderr = ssh_client.exec_command(command)
        output = stdout.read().decode()
        error = stderr.read().decode()

        if error:
            return jsonify({"success": False, "message": error}), 500

        return jsonify({"success": True, "output": output}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
