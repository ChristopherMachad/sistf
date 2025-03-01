from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import os
import logging
from flask_session import Session
import redis

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'chave_secreta_padrao')

# Configuração do Redis
redis_url = os.environ.get('REDIS_URL', 'redis://default:AXbfAAIjcDEwY2JlNGM5Y2M3YmU0M2IwODg3N2RiY2ExN2IyMDdhY3AxMA@striking-wolf-30431.upstash.io:6379')
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = redis.from_url(redis_url, ssl_cert_reqs=None)

# Configurações de sessão e cookies
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='None',
    PERMANENT_SESSION_LIFETIME=timedelta(days=7)
)

# Inicialização do Session
Session(app)

# Configuração do CORS
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": ["http://localhost:8000", "https://sistema-financeiro-frontend.onrender.com", "https://sistema-financeiro3.onrender.com"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-Requested-With", "Accept"],
        "supports_credentials": True,
        "expose_headers": ["Set-Cookie"],
        "max_age": 3600
    }
})

# Configuração do banco de dados
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///financas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Inicialização do banco de dados
with app.app_context():
    db.create_all()
    logger.info("Banco de dados inicializado")

# Modelo de Usuário
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    contas = db.relationship('Conta', backref='usuario', lazy=True)

# Modelo de Conta
class Conta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 'pagar' ou 'receber'
    status = db.Column(db.String(20), default='pendente')  # 'pendente', 'pago', 'recebido'
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)

# Função para verificar se usuário está logado
def requer_login(f):
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session:
            return jsonify({'erro': 'Usuário não está logado'}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# Rotas de Autenticação
@app.route('/api/registrar', methods=['POST'])
def registrar():
    try:
        dados = request.get_json()
        if not dados:
            logger.error("Dados não recebidos no registro")
            return jsonify({'erro': 'Dados não recebidos'}), 400
            
        if not dados.get('username') or not dados.get('password'):
            logger.error("Username ou password não fornecidos")
            return jsonify({'erro': 'Username e password são obrigatórios'}), 400

        if Usuario.query.filter_by(username=dados['username']).first():
            logger.info(f"Tentativa de registro com username já existente: {dados['username']}")
            return jsonify({'erro': 'Nome de usuário já existe'}), 400
        
        novo_usuario = Usuario(
            username=dados['username'],
            password_hash=generate_password_hash(dados['password'])
        )
        db.session.add(novo_usuario)
        db.session.commit()
        logger.info(f"Novo usuário registrado: {dados['username']}")
        return jsonify({'mensagem': 'Usuário criado com sucesso!'})
    except Exception as e:
        logger.error(f"Erro no registro: {str(e)}")
        db.session.rollback()
        return jsonify({'erro': 'Erro interno do servidor'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        dados = request.get_json()
        logger.info("Dados recebidos no login: %s", dados)
        
        if not dados:
            logger.error("Dados não recebidos no login")
            return jsonify({'erro': 'Dados não recebidos'}), 400
            
        if not dados.get('username') or not dados.get('password'):
            logger.error("Username ou password não fornecidos")
            return jsonify({'erro': 'Username e password são obrigatórios'}), 400

        usuario = Usuario.query.filter_by(username=dados['username']).first()
        logger.info("Usuário encontrado: %s", usuario is not None)
        
        if usuario and check_password_hash(usuario.password_hash, dados['password']):
            session.permanent = True
            session['usuario_id'] = usuario.id
            session.modified = True
            
            logger.info("Login bem-sucedido: %s, Session ID: %s", dados['username'], session.sid if hasattr(session, 'sid') else 'N/A')
            response = jsonify({'mensagem': 'Login realizado com sucesso!'})
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            return response
        
        logger.info("Tentativa de login mal-sucedida: %s", dados['username'])
        return jsonify({'erro': 'Usuário ou senha inválidos'}), 401
    except Exception as e:
        logger.error("Erro no login: %s", str(e), exc_info=True)
        return jsonify({'erro': 'Erro interno do servidor', 'detalhes': str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('usuario_id', None)
    return jsonify({'mensagem': 'Logout realizado com sucesso!'})

# Rotas da API
@app.route('/api/contas', methods=['GET'])
@requer_login
def listar_contas():
    contas = Conta.query.filter_by(usuario_id=session['usuario_id']).all()
    return jsonify([{
        'id': conta.id,
        'descricao': conta.descricao,
        'valor': conta.valor,
        'data_vencimento': conta.data_vencimento.strftime('%Y-%m-%d'),
        'tipo': conta.tipo,
        'status': conta.status,
        'data_criacao': conta.data_criacao.strftime('%Y-%m-%d %H:%M:%S')
    } for conta in contas])

@app.route('/api/contas', methods=['POST'])
@requer_login
def criar_conta():
    dados = request.json
    nova_conta = Conta(
        descricao=dados['descricao'],
        valor=dados['valor'],
        data_vencimento=datetime.strptime(dados['data_vencimento'], '%Y-%m-%d'),
        tipo=dados['tipo'],
        status=dados.get('status', 'pendente'),
        usuario_id=session['usuario_id']
    )
    db.session.add(nova_conta)
    db.session.commit()
    return jsonify({'mensagem': 'Conta criada com sucesso!', 'id': nova_conta.id}), 201

@app.route('/api/contas/<int:id>', methods=['PUT'])
@requer_login
def atualizar_conta(id):
    conta = Conta.query.get_or_404(id)
    if conta.usuario_id != session['usuario_id']:
        return jsonify({'erro': 'Acesso negado'}), 403
    
    dados = request.json
    conta.descricao = dados.get('descricao', conta.descricao)
    conta.valor = dados.get('valor', conta.valor)
    if 'data_vencimento' in dados:
        conta.data_vencimento = datetime.strptime(dados['data_vencimento'], '%Y-%m-%d')
    conta.tipo = dados.get('tipo', conta.tipo)
    conta.status = dados.get('status', conta.status)
    
    db.session.commit()
    return jsonify({'mensagem': 'Conta atualizada com sucesso!'})

@app.route('/api/contas/<int:id>', methods=['DELETE'])
@requer_login
def deletar_conta(id):
    conta = Conta.query.get_or_404(id)
    if conta.usuario_id != session['usuario_id']:
        return jsonify({'erro': 'Acesso negado'}), 403
    
    db.session.delete(conta)
    db.session.commit()
    return jsonify({'mensagem': 'Conta deletada com sucesso!'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 