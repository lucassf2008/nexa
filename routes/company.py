from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from models import (
    db, CompanyProfile, Job, Application, Notification
)
from auth import login_required
from routes import save_uploaded_image, safe_form_str

company_bp = Blueprint('company', __name__)


@company_bp.route('/perfil/empresa')
@login_required
def my_company_profile():
    user = g.current_user
    if user.role == 'empresa' and user.company_profile:
        return redirect(url_for('company.profile_view', company_id=user.company_profile.id))
    # Se outro perfil estiver navegando pelo menu
    first_company = CompanyProfile.query.filter_by(is_authorized=True).first()
    if first_company:
        return redirect(url_for('company.profile_view', company_id=first_company.id))
    flash('Nenhuma empresa encontrada.', 'warning')
    return redirect(url_for('main.feed'))


@company_bp.route('/empresa/<int:company_id>')
def profile_view(company_id):
    company = CompanyProfile.query.get_or_404(company_id)
    is_owner = (g.current_user and g.current_user.id == company.user_id)
    is_following = False

    if g.current_user:
        is_following = any(f.follower_id == g.current_user.id for f in company.followers)

    # Vagas da empresa
    jobs = company.jobs.all()

    return render_template(
        'profile_company.html',
        company=company,
        jobs=jobs,
        is_owner=is_owner,
        is_following=is_following
    )


@company_bp.route('/empresa/editar', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user = g.current_user
    if user.role != 'empresa' or not user.company_profile:
        flash('Acesso restrito ao perfil corporativo.', 'danger')
        return redirect(url_for('main.feed'))

    company = user.company_profile

    if request.method == 'POST':
        name = safe_form_str(request.form, 'name', company.name)
        headline = safe_form_str(request.form, 'headline', company.headline)
        if not name or not headline:
            flash('Razão social e headline institucional são obrigatórias.', 'danger')
            return render_template('edit_company_profile.html', company=company)

        company.name = name
        company.headline = headline
        company.description = safe_form_str(request.form, 'description', company.description)
        company.sector = safe_form_str(request.form, 'sector', company.sector)
        company.location = safe_form_str(request.form, 'location', company.location)
        company.employee_count = safe_form_str(request.form, 'employee_count', company.employee_count)
        company.website = safe_form_str(request.form, 'website', company.website)
        company.contact_email = safe_form_str(request.form, 'contact_email', company.contact_email)
        company.contact_phone = safe_form_str(request.form, 'contact_phone', company.contact_phone)
        company.facebook = safe_form_str(request.form, 'facebook', company.facebook)
        company.instagram = safe_form_str(request.form, 'instagram', company.instagram)
        company.twitter = safe_form_str(request.form, 'twitter', company.twitter)
        company.linkedin = safe_form_str(request.form, 'linkedin', company.linkedin)

        # Upload de logo e banner
        logo_url, logo_err = save_uploaded_image(request.files.get('logo'), f"company_logo_{company.id}")
        if logo_err:
            flash(f'Logo: {logo_err}', 'warning')
        elif logo_url:
            company.logo_url = logo_url

        banner_url, banner_err = save_uploaded_image(request.files.get('banner'), f"company_banner_{company.id}")
        if banner_err:
            flash(f'Banner: {banner_err}', 'warning')
        elif banner_url:
            company.banner_url = banner_url

        db.session.commit()
        flash('Perfil empresarial atualizado com sucesso!', 'success')
        return redirect(url_for('company.profile_view', company_id=company.id))

    return render_template('edit_company_profile.html', company=company)


@company_bp.route('/empresa/vagas/nova', methods=['GET', 'POST'])
@login_required
def create_job():
    user = g.current_user
    if user.role != 'empresa' or not user.company_profile:
        flash('Apenas empresas autorizadas podem publicar vagas.', 'danger')
        return redirect(url_for('jobs.list_jobs'))

    company = user.company_profile

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        requirements = request.form.get('requirements', '').strip()
        area = request.form.get('area', 'Desenvolvimento de software').strip()
        job_type = request.form.get('job_type', 'Estágio').strip()
        modality = request.form.get('modality', 'Presencial').strip()
        location = request.form.get('location', company.location).strip()
        salary = request.form.get('salary', '').strip()
        benefits = request.form.get('benefits', '').strip()
        vacancies = request.form.get('vacancies', '1').strip()
        experience_level = request.form.get('experience_level', 'Estágio').strip()

        if not title or not description:
            flash('Título e descrição da vaga são obrigatórios.', 'danger')
            return render_template('company_new_job.html', company=company, form_data=request.form)

        job = Job(
            company_id=company.id,
            title=title,
            description=description,
            requirements=requirements or None,
            area=area,
            job_type=job_type,
            modality=modality,
            location=location,
            salary=salary or None,
            benefits=benefits or None,
            vacancies=max(1, int(vacancies)) if vacancies.isdigit() else 1,
            experience_level=experience_level,
            image_url=company.logo_url or '/static/images/job_default.jpg'
        )
        db.session.add(job)
        db.session.commit()

        # Notificar seguidores da empresa sobre a nova vaga
        for follow in company.followers:
            notif = Notification(
                user_id=follow.follower_id,
                title=f"Nova vaga em {company.name}",
                message=f"{company.name} publicou a vaga: '{job.title}'. Confira agora!",
                link=url_for('jobs.job_detail', job_id=job.id)
            )
            db.session.add(notif)
        db.session.commit()

        flash(f'Vaga "{job.title}" publicada com sucesso!', 'success')
        return redirect(url_for('company.profile_view', company_id=company.id))

    return render_template('company_new_job.html', company=company)


@company_bp.route('/empresa/vagas/<int:job_id>/deletar', methods=['POST'])
@login_required
def delete_job(job_id):
    user = g.current_user
    job = Job.query.get_or_404(job_id)

    # Verifica se o usuário é o proprietário da vaga
    if (
        user.role != 'empresa'
        or not user.company_profile
        or user.company_profile.id != job.company_id
    ):
        abort(403)

    company_id = job.company_id
    job_title = job.title

    try:
        db.session.delete(job)
        db.session.commit()

        flash(
            f'Vaga "{job_title}" excluída com sucesso!',
            'success'
        )

    except Exception:
        db.session.rollback()
        flash(
            'Não foi possível excluir a vaga.',
            'danger'
        )

    return redirect(
        url_for('company.profile_view', company_id=company_id)
    )


@company_bp.route('/empresa/vagas/<int:job_id>/candidatos')
@login_required
def job_candidates(job_id):
    user = g.current_user
    job = Job.query.get_or_404(job_id)

    # Apenas a dona da vaga ou admin
    if user.role != 'admin' and (user.role != 'empresa' or not user.company_profile or user.company_profile.id != job.company_id):
        flash('Você não tem permissão para visualizar estes candidatos.', 'danger')
        return redirect(url_for('main.feed'))

    status_filter = request.args.get('status')
    candidates_query = job.applications.order_by(Application.created_at.desc())
    if status_filter:
        candidates_query = candidates_query.filter_by(status=status_filter)
    applications = candidates_query.all()

    return render_template(
        'company_candidates.html',
        job=job,
        applications=applications,
        current_status=status_filter or 'todos'
    )


@company_bp.route('/empresa/candidatura/<int:app_id>/status', methods=['POST'])
@login_required
def update_application_status(app_id):
    application = Application.query.get_or_404(app_id)
    user = g.current_user

    if user.role != 'admin' and (user.role != 'empresa' or not user.company_profile or user.company_profile.id != application.job.company_id):
        abort(403)

    new_status = request.form.get('status')
    feedback_notes = request.form.get('notes', '').strip()

    valid_statuses = ['recebida', 'em_analise', 'entrevista', 'aprovada', 'rejeitada']
    if new_status in valid_statuses:
        application.status = new_status
        if feedback_notes:
            application.notes = feedback_notes

        # Notificar aluno sobre a mudança de status
        status_labels = {
            'recebida': 'Recebida',
            'em_analise': 'Em análise',
            'entrevista': 'Convocação para Entrevista',
            'aprovada': 'Aprovada!',
            'rejeitada': 'Encerrada'
        }
        notif = Notification(
            user_id=application.student.user_id,
            title='Atualização de Candidatura',
            message=f"Seu status na vaga '{application.job.title}' mudou para: {status_labels.get(new_status, new_status)}.",
            link=url_for('jobs.job_detail', job_id=application.job.id)
        )
        db.session.add(notif)
        db.session.commit()
        flash('Status da candidatura atualizado com sucesso!', 'success')

    return redirect(url_for('company.job_candidates', job_id=application.job_id))
