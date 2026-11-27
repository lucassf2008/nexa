import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shutil
import tempfile
import unittest
from app import create_app
from config import Config
from models import db, User, StudentProfile, CompanyProfile, Job, Application, Post, Message, AuthorizedStudent
from forms import validate_cpf, validate_cnpj, clean_digits
from seed import make_valid_cpf

class NexaSenaiTestCase(unittest.TestCase):
    def setUp(self):
        # Cada teste usa um banco SQLite temporário e limpo (o banco real nexa_senai.db não é tocado)
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        # ...e uma pasta de uploads temporária, para que os testes nunca apaguem arquivos reais
        self.upload_dir = tempfile.mkdtemp()

        class TestConfig(Config):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{self.db_path}"
            UPLOAD_FOLDER = self.upload_dir

        self.app = create_app(TestConfig)
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        shutil.rmtree(self.upload_dir, ignore_errors=True)

    def test_algorithms_cpf_cnpj(self):
        """Testa os algoritmos matemáticos de CPF e CNPJ"""
        # CPFs matematicamente válidos
        self.assertTrue(validate_cpf("234.567.890-92"))
        self.assertTrue(validate_cpf("34567890175"))
        # CPFs inválidos
        self.assertFalse(validate_cpf("111.111.111-11"))
        self.assertFalse(validate_cpf("123.456.789-00"))
        self.assertFalse(validate_cpf("123"))

        # CNPJs matematicamente válidos
        self.assertTrue(validate_cnpj("11.222.333/0001-81"))
        self.assertTrue(validate_cnpj("55666777000181"))
        # CNPJs inválidos
        self.assertFalse(validate_cnpj("00.000.000/0000-00"))
        self.assertFalse(validate_cnpj("11.222.333/0001-00"))

    def test_routes_public(self):
        """Testa se rotas públicas e de login respondem com 200"""
        res = self.client.get('/login')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Login', res.data)
        self.assertIn(b'Nexa', res.data)

        res = self.client.get('/cadastro')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Criar Conta de Aluno', res.data)

        res = self.client.get('/vagas')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Encontre sua pr', res.data)
        self.assertIn(b'Filtros', res.data)

    def test_login_aluno(self):
        """Testa o login com credenciais de aluno"""
        res = self.client.post('/login', data={
            'login_type': 'aluno',
            'identifier': '234.567.890-92',
            'password': 'senai123'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CLARISSE LIMA MOURA', res.data)

    def test_login_empresa(self):
        """Testa o login corporativo com CNPJ e código autorizado"""
        res = self.client.post('/login', data={
            'login_type': 'empresa',
            'cnpj': '11.222.333/0001-81',
            'access_code': 'TECH-2024'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'TechCorp', res.data)

    def test_login_admin(self):
        """Testa o login no painel administrativo"""
        res = self.client.post('/login', data={
            'login_type': 'admin',
            'email': 'admin@senai.br',
            'password': 'admin123'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Painel de Administra', res.data)

    def test_vagas_filters(self):
        """Testa filtros reais de vagas"""
        res = self.client.get('/vagas?area=Desenvolvimento+de+software')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Estagi', res.data)

    def test_student_profile(self):
        """Testa a visualização da tela de perfil de aluno"""
        # Login primeiro
        self.client.post('/login', data={
            'login_type': 'aluno',
            'identifier': 'clarisse.moura@aluno.senai.br',
            'password': 'senai123'
        })
        res = self.client.get('/perfil/aluno')
        self.assertEqual(res.status_code, 302)  # redireciona para o id do aluno
        res = self.client.get('/perfil/aluno', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CLARISSE LIMA MOURA', res.data)
        self.assertIn(b'Sobre Mim', res.data)
        self.assertIn(b'Experi', res.data)
        self.assertIn(b'Novas Mensagens', res.data)

    def test_messaging_flow(self):
        """Testa envio de mensagem entre usuários"""
        # Login como aluno
        self.client.post('/login', data={
            'login_type': 'aluno',
            'identifier': 'clarisse.moura@aluno.senai.br',
            'password': 'senai123'
        })
        # Envia mensagem para o TechCorp (user_id 7 ou similar)
        with self.app.app_context():
            techcorp = CompanyProfile.query.filter_by(name='TechCorp Inovações S.A.').first()
            target_id = techcorp.user_id

        res = self.client.post('/mensagens/enviar', data={
            'receiver_id': target_id,
            'content': 'Olá, gostaria de tirar uma dúvida sobre a vaga de engenheiro de software!'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

    def test_navbar_links_by_role(self):
        """Testa se o cabeçalho exibe apenas o link de perfil correspondente ao tipo de usuário"""
        # Sem login: não exibe nem Perfil do Aluno nem Perfil da Empresa
        res = self.client.get('/vagas')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(b'Perfil do Aluno', res.data)
        self.assertNotIn(b'Perfil da Empresa', res.data)

        # Login como aluno: exibe Perfil do Aluno, oculta Perfil da Empresa
        self.client.post('/login', data={
            'login_type': 'aluno',
            'identifier': '234.567.890-92',
            'password': 'senai123'
        })
        res = self.client.get('/vagas')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Perfil do Aluno', res.data)
        self.assertNotIn(b'Perfil da Empresa', res.data)
        self.client.get('/logout')

        # Login como empresa: exibe Perfil da Empresa, oculta Perfil do Aluno
        self.client.post('/login', data={
            'login_type': 'empresa',
            'cnpj': '11.222.333/0001-81',
            'access_code': 'TECH-2024'
        })
        res = self.client.get('/vagas')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Perfil da Empresa', res.data)
        self.assertNotIn(b'Perfil do Aluno', res.data)
        self.client.get('/logout')

        # Login como admin: oculta ambos e exibe Painel Admin
        self.client.post('/login', data={
            'login_type': 'admin',
            'email': 'admin@senai.br',
            'password': 'admin123'
        })
        res = self.client.get('/vagas')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Painel Admin', res.data)
        self.assertNotIn(b'Perfil do Aluno', res.data)
        self.assertNotIn(b'Perfil da Empresa', res.data)

    def test_only_clarisse_seeded_and_preregistration_required(self):
        """Testa que apenas Clarisse existe como aluna inicial e que o cadastro exige pré-cadastro no Admin"""
        with self.app.app_context():
            students = StudentProfile.query.all()
            self.assertEqual(len(students), 1)
            self.assertEqual(students[0].full_name, 'CLARISSE LIMA MOURA')

        new_cpf = make_valid_cpf('888777666')
        new_email = 'novo.aluno@aluno.senai.br'

        # 1. Tentativa de cadastro sem pré-cadastro no painel admin deve falhar
        res = self.client.post('/cadastro', data={
            'full_name': 'Novo Aluno Teste',
            'cpf': new_cpf,
            'birth_date': '2003-05-10',
            'email': new_email,
            'senai_course': 'Técnico em Desenvolvimento de Sistemas',
            'professional_area': 'Desenvolvimento de software',
            'password': 'password123',
            'password_confirm': 'password123'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'autorizados', res.data)
        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(email=new_email).first())

        # 2. Admin pré-cadastra CPF e e-mail no painel administrativo
        self.client.post('/login', data={
            'login_type': 'admin',
            'email': 'admin@senai.br',
            'password': 'admin123'
        })
        res = self.client.post('/admin/alunos-autorizados', data={
            'cpf': new_cpf,
            'email': new_email
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(new_email.encode('utf-8'), res.data)
        self.client.get('/logout')

        # 3. Tentativa com e-mail divergente do pré-cadastrado deve falhar
        res = self.client.post('/cadastro', data={
            'full_name': 'Novo Aluno Teste',
            'cpf': new_cpf,
            'birth_date': '2003-05-10',
            'email': 'outro@aluno.senai.br',
            'senai_course': 'Técnico em Desenvolvimento de Sistemas',
            'professional_area': 'Desenvolvimento de software',
            'password': 'password123',
            'password_confirm': 'password123'
        }, follow_redirects=True)
        self.assertIn(b'autorizados', res.data)

        # 4. Cadastro com CPF e e-mail pré-cadastrados deve funcionar
        res = self.client.post('/cadastro', data={
            'full_name': 'Novo Aluno Teste',
            'cpf': new_cpf,
            'birth_date': '2003-05-10',
            'email': new_email,
            'senai_course': 'Técnico em Desenvolvimento de Sistemas',
            'professional_area': 'Desenvolvimento de software',
            'password': 'password123',
            'password_confirm': 'password123'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Novo Aluno Teste', res.data)
        with self.app.app_context():
            auth_entry = AuthorizedStudent.query.filter_by(email=new_email).first()
            self.assertIsNotNone(auth_entry)
            self.assertTrue(auth_entry.is_used)

    def _login_admin(self):
        self.client.post('/login', data={
            'login_type': 'admin',
            'email': 'admin@senai.br',
            'password': 'admin123'
        })

    def test_admin_delete_student_profile(self):
        """Admin exclui um perfil de aluno e todos os dados vinculados (CRUD - Delete)"""
        with self.app.app_context():
            student = StudentProfile.query.first()
            student_id, user_id, cpf = student.id, student.user_id, student.cpf

        self._login_admin()
        page = self.client.get('/admin/usuarios')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'openDeleteModal', page.data)

        res = self.client.post(f'/admin/alunos/{student_id}/deletar', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'exclu', res.data)
        with self.app.app_context():
            self.assertIsNone(db.session.get(User, user_id))
            self.assertIsNone(db.session.get(StudentProfile, student_id))
            self.assertEqual(Application.query.filter_by(student_id=student_id).count(), 0)
            self.assertEqual(
                Message.query.filter((Message.sender_id == user_id) | (Message.receiver_id == user_id)).count(), 0
            )

    def test_delete_student_removes_uploaded_photo_only(self):
        """A foto enviada pelo aluno é apagada do disco; imagens padrão do sistema são preservadas"""
        photo = os.path.join(self.upload_dir, 'avatar_student_1_teste.jpg')
        with open(photo, 'wb') as fh:
            fh.write(b'fake-image')
        with self.app.app_context():
            student = StudentProfile.query.first()
            student.avatar_url = '/static/uploads/avatar_student_1_teste.jpg'
            student.banner_url = '/static/images/default_banner.jpg'
            student_id = student.id
            db.session.commit()

        self._login_admin()
        self.client.post(f'/admin/alunos/{student_id}/deletar')
        self.assertFalse(os.path.exists(photo))
        self.assertTrue(os.path.exists(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'static', 'images', 'default_banner.jpg')))

    def test_admin_delete_company_profile(self):
        """Admin exclui uma empresa junto com suas vagas e candidaturas"""
        with self.app.app_context():
            company = CompanyProfile.query.first()
            company_id, user_id = company.id, company.user_id

        self._login_admin()
        res = self.client.post(f'/admin/empresas/{company_id}/deletar', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(db.session.get(User, user_id))
            self.assertIsNone(db.session.get(CompanyProfile, company_id))
            self.assertEqual(Job.query.filter_by(company_id=company_id).count(), 0)

    def test_delete_profile_requires_admin(self):
        """Visitantes e alunos não podem excluir perfis"""
        with self.app.app_context():
            student_id = StudentProfile.query.first().id
            company_id = CompanyProfile.query.first().id

        # Sem login
        self.client.post(f'/admin/alunos/{student_id}/deletar')
        self.client.post(f'/admin/empresas/{company_id}/deletar')

        # Logado como aluno
        self.client.post('/login', data={
            'login_type': 'aluno',
            'identifier': '234.567.890-92',
            'password': 'senai123'
        })
        res = self.client.post(f'/admin/alunos/{student_id}/deletar')
        self.assertIn(res.status_code, (302, 403))

        with self.app.app_context():
            self.assertIsNotNone(db.session.get(StudentProfile, student_id))
            self.assertIsNotNone(db.session.get(CompanyProfile, company_id))

    def test_deleted_student_can_be_preregistered_again(self):
        """Ao excluir um aluno, o pré-cadastro usado é liberado (CPF/e-mail podem voltar)"""
        with self.app.app_context():
            student = StudentProfile.query.first()
            student_id, cpf, email = student.id, student.cpf, student.user.email
            if not AuthorizedStudent.query.filter_by(email=email).first():
                db.session.add(AuthorizedStudent(cpf=cpf, email=email, is_used=True))
                db.session.commit()
            self.assertIsNotNone(AuthorizedStudent.query.filter_by(email=email).first())

        self._login_admin()
        self.client.post(f'/admin/alunos/{student_id}/deletar')
        with self.app.app_context():
            self.assertIsNone(AuthorizedStudent.query.filter_by(email=email).first())

    def test_admin_pages_are_mobile_ready(self):
        """Páginas do admin têm viewport, tabelas responsivas e CSS mobile"""
        self._login_admin()
        for url in ('/admin/', '/admin/usuarios', '/admin/empresas', '/admin/vagas'):
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200, url)
            self.assertIn(b'width=device-width', res.data)
            self.assertIn(b'responsive.css', res.data)
        for url in ('/admin/usuarios', '/admin/empresas', '/admin/vagas'):
            self.assertIn(b'admin-table', self.client.get(url).data, url)

if __name__ == '__main__':
    unittest.main()
