import os
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, current_app
from models import (
    db, User, StudentProfile, CompanyProfile, Job, Application, Post, Report, AuthorizedStudent,
    Message, Connection, Follow
)
from auth import login_required, role_required
from forms import clean_digits, validate_cpf, format_cpf, validate_cnpj, format_cnpj, validate_email_format

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def generate_company_code(prefix="NEXA"):
    # Gera um código seguro e legível como NEXA-9482-BR
    rand_part = secrets.token_hex(3).upper()
    return f"{prefix}-{rand_part}"


def _upload_path(url):
    """Converte uma URL '/static/uploads/arquivo.png' no caminho físico do arquivo.
    Só retorna caminhos dentro da pasta de uploads (imagens padrão do sistema são preservadas)."""
    if not url or not url.startswith('/static/uploads/'):
        return None
    upload_dir = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    path = os.path.abspath(os.path.join(upload_dir, os.path.basename(url)))
    return path if path.startswith(upload_dir + os.sep) else None


def _purge_user(user):
    """Remove um usuário e TODOS os dados ligados a ele (perfil, vagas, candidaturas,
    publicações, mensagens, conexões, seguidores e notificações).

    Retorna a lista de arquivos enviados (uploads) que devem ser apagados do disco
    depois que o commit for concluído com sucesso."""
    files = []
    profile = user.student_profile or user.company_profile
    if profile:
        for attr in ('avatar_url', 'banner_url', 'logo_url'):
            files.append(_upload_path(getattr(profile, attr, None)))
    for post in user.posts:
        files.append(_upload_path(post.image_url))
        # Denúncias que apontam para a publicação ficam sem referência (não são apagadas)
        Report.query.filter_by(post_id=post.id).update({'post_id': None}, synchronize_session=False)

    # Tabelas sem cascade automático no modelo: limpeza explícita
    Message.query.filter(
        (Message.sender_id == user.id) | (Message.receiver_id == user.id)
    ).delete(synchronize_session=False)
    Connection.query.filter(
        (Connection.requester_id == user.id) | (Connection.addressee_id == user.id)
    ).delete(synchronize_session=False)
    Follow.query.filter_by(follower_id=user.id).delete(synchronize_session=False)
    Report.query.filter_by(reporter_id=user.id).delete(synchronize_session=False)
    Report.query.filter_by(reported_user_id=user.id).update({'reported_user_id': None}, synchronize_session=False)

    # Libera o pré-cadastro (CPF / e-mail) para que o aluno possa se cadastrar de novo, se necessário
    if user.student_profile:
        cpf = user.student_profile.cpf
        AuthorizedStudent.query.filter(
            (AuthorizedStudent.cpf == cpf) | (AuthorizedStudent.email == user.email)
        ).delete(synchronize_session=False)

    db.session.flush()
    db.session.expire_all()
    db.session.delete(db.session.get(User, user.id))
    return [f for f in files if f]


def _remove_files(paths):
    for path in paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            current_app.logger.warning('Não foi possível remover o arquivo %s', path)


@admin_bp.route('/')
@login_required
@role_required('admin')
def dashboard():
    total_students = StudentProfile.query.count()
    total_companies = CompanyProfile.query.count()
    total_jobs = Job.query.count()
    total_applications = Application.query.count()
    total_posts = Post.query.count()
    pending_reports = Report.query.filter_by(status='pendente').count()

    recent_companies = CompanyProfile.query.order_by(CompanyProfile.created_at.desc()).limit(5).all()
    recent_students = StudentProfile.query.order_by(StudentProfile.id.desc()).limit(5).all()
    recent_jobs = Job.query.order_by(Job.created_at.desc()).limit(5).all()

    return render_template(
        'admin/dashboard.html',
        total_students=total_students,
        total_companies=total_companies,
        total_jobs=total_jobs,
        total_applications=total_applications,
        total_posts=total_posts,
        pending_reports=pending_reports,
        recent_companies=recent_companies,
        recent_students=recent_students,
        recent_jobs=recent_jobs
    )


@admin_bp.route('/empresas', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def companies():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        cnpj_raw = request.form.get('cnpj', '').strip()
        email = request.form.get('email', '').strip().lower()
        sector = request.form.get('sector', 'Indústria e Tecnologia').strip()
        location = request.form.get('location', 'São Paulo - SP').strip()
        custom_code = request.form.get('access_code', '').strip()

        if not name or not cnpj_raw or not email:
            flash('Nome, CNPJ e e-mail institucional são obrigatórios.', 'danger')
            return redirect(url_for('admin.companies'))

        cnpj_clean = clean_digits(cnpj_raw)
        if not validate_cnpj(cnpj_clean):
            flash('O CNPJ informado é inválido de acordo com o cálculo matemático oficial da Receita Federal.', 'danger')
            return redirect(url_for('admin.companies'))

        formatted_c = format_cnpj(cnpj_clean)

        # Checar se já existe
        if CompanyProfile.query.filter((CompanyProfile.cnpj == cnpj_clean) | (CompanyProfile.cnpj == formatted_c)).first():
            flash('Uma empresa com este CNPJ já está registrada no Nexa SENAI.', 'danger')
            return redirect(url_for('admin.companies'))

        if User.query.filter_by(email=email).first():
            flash('Já existe um usuário com este e-mail.', 'danger')
            return redirect(url_for('admin.companies'))

        # Gerar código de acesso empresarial único
        access_code = custom_code or generate_company_code()

        # Criação do usuário da empresa
        emp_user = User(
            role='empresa',
            email=email,
            is_active=True
        )
        emp_user.set_password(access_code)  # Senha inicial pode ser o próprio código
        db.session.add(emp_user)
        db.session.flush()

        # Criação do perfil da empresa
        new_company = CompanyProfile(
            user_id=emp_user.id,
            name=name,
            cnpj=formatted_c,
            access_code=access_code,
            is_authorized=True,
            is_blocked=False,
            sector=sector,
            location=location,
            contact_email=email,
            headline=f'Empresa Parceira Oficial do SENAI em {sector}',
            description=f'Empresa {name} integrada ao ecossistema Nexa SENAI para fomento de estágios, carreiras e inovação industrial.'
        )
        db.session.add(new_company)
        db.session.commit()

        flash(f'Empresa "{name}" autorizada com sucesso! Código de acesso gerado: {access_code}', 'success')
        return redirect(url_for('admin.companies'))

    all_companies = CompanyProfile.query.order_by(CompanyProfile.created_at.desc()).all()
    return render_template('admin/companies.html', companies=all_companies)


@admin_bp.route('/empresas/<int:company_id>/toggle-status', methods=['POST'])
@login_required
@role_required('admin')
def toggle_company_status(company_id):
    company = CompanyProfile.query.get_or_404(company_id)
    company.is_blocked = not company.is_blocked
    company.user.is_active = not company.is_blocked
    db.session.commit()

    status_str = "bloqueada" if company.is_blocked else "desbloqueada/ativa"
    flash(f'Empresa {company.name} foi {status_str} com sucesso.', 'info')
    return redirect(url_for('admin.companies'))


@admin_bp.route('/empresas/<int:company_id>/redefinir-codigo', methods=['POST'])
@login_required
@role_required('admin')
def reset_company_code(company_id):
    company = CompanyProfile.query.get_or_404(company_id)
    new_code = generate_company_code()
    company.access_code = new_code
    company.user.set_password(new_code)
    db.session.commit()

    flash(f'Novo código de acesso para a empresa {company.name}: {new_code}', 'success')
    return redirect(url_for('admin.companies'))


@admin_bp.route('/empresas/<int:company_id>/deletar', methods=['POST'])
@login_required
@role_required('admin')
def delete_company(company_id):
    company = CompanyProfile.query.get_or_404(company_id)
    name = company.name
    try:
        files = _purge_user(company.user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Falha ao excluir a empresa %s', company_id)
        flash('Não foi possível excluir a empresa. Nenhum dado foi alterado.', 'danger')
        return redirect(url_for('admin.companies'))

    _remove_files(files)
    flash(f'Empresa "{name}" excluída permanentemente, junto com suas vagas e candidaturas.', 'info')
    return redirect(url_for('admin.companies'))


@admin_bp.route('/usuarios')
@login_required
@role_required('admin')
def users_list():
    students = StudentProfile.query.all()
    companies = CompanyProfile.query.all()
    authorized_students = AuthorizedStudent.query.order_by(AuthorizedStudent.created_at.desc()).all()
    return render_template(
        'admin/users.html',
        students=students,
        companies=companies,
        authorized_students=authorized_students
    )


@admin_bp.route('/alunos-autorizados', methods=['POST'])
@login_required
@role_required('admin')
def authorize_student():
    cpf_raw = request.form.get('cpf', '').strip()
    email = request.form.get('email', '').strip().lower()

    if not cpf_raw or not email:
        flash('CPF e e-mail são obrigatórios para o pré-cadastro do aluno.', 'danger')
        return redirect(url_for('admin.users_list'))

    cpf_clean = clean_digits(cpf_raw)
    if not validate_cpf(cpf_clean):
        flash('O CPF informado é inválido pelo algoritmo de validação matemática.', 'danger')
        return redirect(url_for('admin.users_list'))

    if not validate_email_format(email):
        flash('Formato de e-mail inválido.', 'danger')
        return redirect(url_for('admin.users_list'))

    formatted_c = format_cpf(cpf_clean)

    if AuthorizedStudent.query.filter(
        (AuthorizedStudent.cpf == formatted_c) | (AuthorizedStudent.email == email)
    ).first():
        flash('Este CPF ou e-mail já está pré-cadastrado na lista de alunos autorizados.', 'warning')
        return redirect(url_for('admin.users_list'))

    if StudentProfile.query.filter(
        (StudentProfile.cpf == cpf_clean) | (StudentProfile.cpf == formatted_c)
    ).first() or User.query.filter_by(email=email).first():
        flash('Já existe uma conta cadastrada com este CPF ou e-mail.', 'warning')
        return redirect(url_for('admin.users_list'))

    auth_entry = AuthorizedStudent(cpf=formatted_c, email=email, is_used=False)
    db.session.add(auth_entry)
    db.session.commit()

    flash(f'Pré-cadastro realizado! O aluno ({formatted_c} / {email}) já pode criar sua conta.', 'success')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/alunos-autorizados/<int:auth_id>/deletar', methods=['POST'])
@login_required
@role_required('admin')
def delete_authorized_student(auth_id):
    auth_entry = AuthorizedStudent.query.get_or_404(auth_id)
    if auth_entry.is_used:
        flash('Não é possível remover um pré-cadastro que já foi utilizado por um aluno.', 'warning')
        return redirect(url_for('admin.users_list'))

    db.session.delete(auth_entry)
    db.session.commit()
    flash('Pré-cadastro removido com sucesso.', 'info')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/usuarios/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@role_required('admin')
def toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == g.current_user.id:
        flash('Você não pode desativar seu próprio usuário administrador.', 'danger')
        return redirect(url_for('admin.users_list'))

    user.is_active = not user.is_active
    db.session.commit()
    flash(f'Usuário {user.display_name} foi {"reativado" if user.is_active else "bloqueado"}.', 'info')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/alunos/<int:student_id>/deletar', methods=['POST'])
@login_required
@role_required('admin')
def delete_student(student_id):
    student = StudentProfile.query.get_or_404(student_id)
    if student.user.id == g.current_user.id or student.user.role != 'aluno':
        flash('Este perfil não pode ser excluído por esta função.', 'danger')
        return redirect(url_for('admin.users_list'))

    name = student.full_name
    try:
        files = _purge_user(student.user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Falha ao excluir o aluno %s', student_id)
        flash('Não foi possível excluir o perfil. Nenhum dado foi alterado.', 'danger')
        return redirect(url_for('admin.users_list'))

    _remove_files(files)
    flash(f'Perfil de "{name}" excluído permanentemente.', 'info')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/vagas')
@login_required
@role_required('admin')
def jobs_list():
    jobs = Job.query.order_by(Job.created_at.desc()).all()
    return render_template('admin/jobs.html', jobs=jobs)


@admin_bp.route('/vagas/<int:job_id>/deletar', methods=['POST'])
@login_required
@role_required('admin')
def delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    title = job.title
    db.session.delete(job)
    db.session.commit()
    flash(f'Vaga "{title}" removida com sucesso.', 'info')
    return redirect(url_for('admin.jobs_list'))


@admin_bp.route('/publicacoes/<int:post_id>/deletar', methods=['POST'])
@login_required
@role_required('admin')
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash('Publicação removida pela moderação administrativa.', 'info')
    return redirect(request.referrer or url_for('admin.dashboard'))
