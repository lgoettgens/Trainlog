import logging
from datetime import datetime

from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify

from src.pg import pg_session
from src.sql import feature_requests as fr_sql
from src.utils import getUser, isCurrentTrip, lang, owner_required, owner, post_to_discord

logger = logging.getLogger(__name__)

feature_requests_blueprint = Blueprint("feature_requests", __name__)


@feature_requests_blueprint.route("/feature_requests")
def feature_requests(username=None):
    """Display feature requests page, with voting if user is logged in"""
    userinfo = session.get("userinfo", {})
    current_user = userinfo.get("logged_in_user")
    
    # Get sort parameter (default to score)
    sort_by = request.args.get('sort', 'score')
    
    with pg_session() as pg:
        if current_user:
            # Get requests with user's votes
            if sort_by == 'date':
                result = pg.execute(
                    fr_sql.list_feature_requests_with_votes_by_date(),
                    {"username": current_user}
                ).fetchall()
            else:
                result = pg.execute(
                    fr_sql.list_feature_requests_with_votes(),
                    {"username": current_user}
                ).fetchall()
        else:
            # Get requests without user votes
            if sort_by == 'date':
                result = pg.execute(fr_sql.list_feature_requests_by_date()).fetchall()
            else:
                result = pg.execute(fr_sql.list_feature_requests()).fetchall()
        
        # Convert to list of dictionaries
        request_list = []
        for req in result:
            if req[3] == owner:
                author_display='admin'
            else: 
                author_display = req[3]
            request_dict = {
                'id': req[0],
                'title': req[1],
                'description': req[2],
                'author_display': author_display,
                'status': req[4],
                'created': req[5],
                'upvotes': req[6],
                'downvotes': req[7],
                'score': req[8],
                'user_vote': req[9] if len(req) > 9 else 0
            }
            request_list.append(request_dict)

    return render_template(
        'feature_requests.html',
        username=current_user,
        requests=request_list,
        current_sort=sort_by,
        **lang.get(userinfo.get("lang", "en"), {}),
        **userinfo,
        nav="bootstrap/navigation.html" if current_user != "public" else "bootstrap/no_user_nav.html",
        isCurrent=isCurrentTrip(getUser()) if current_user != "public" else False
    )


@feature_requests_blueprint.route("/feature_requests/<int:request_id>")
def single_feature_request(request_id):
    """Display a single feature request page"""
    userinfo = session.get("userinfo", {})
    current_user = userinfo.get("logged_in_user")
    
    with pg_session() as pg:
        if current_user:
            # Get request with user's vote
            result = pg.execute(
                fr_sql.get_single_feature_request_with_vote(),
                {"request_id": request_id, "username": current_user}
            ).fetchone()
        else:
            # Get request without user vote
            result = pg.execute(
                fr_sql.get_single_feature_request(),
                {"request_id": request_id}
            ).fetchone()
        
        if not result:
            return render_template('404.html'), 404
        
        # Convert to dictionary
        if result[3] == owner:
            author_display = 'admin'
        else:
            author_display = result[3]
            
        request_dict = {
            'id': result[0],
            'title': result[1],
            'description': result[2],
            'author_display': author_display,
            'status': result[4],
            'created': result[5],
            'upvotes': result[6],
            'downvotes': result[7],
            'score': result[8],
            'user_vote': result[9] if len(result) > 9 else 0
        }

    return render_template(
        'single_feature_request.html',
        username=current_user,
        request=request_dict,
        **lang.get(userinfo.get("lang", "en"), {}),
        **userinfo,
        nav="bootstrap/navigation.html" if current_user != "public" else "bootstrap/no_user_nav.html",
        isCurrent=isCurrentTrip(getUser()) if current_user != "public" else False
    )


def login_required(f):
    """Decorator to require login - implement according to your auth system"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("userinfo", {}).get("logged_in_user"):
            return redirect(url_for("feature_requests"))
        return f(*args, **kwargs)
    return decorated_function


@feature_requests_blueprint.route("/<username>/feature_requests/submit", methods=["POST"])
@login_required
def submit_feature_request(username):
    """Submit a new feature request"""
    title = request.form["title"]
    description = request.form["description"]
    current_user = session["userinfo"]["logged_in_user"]
    is_owner = session["userinfo"].get("is_owner", False)
    display_name = current_user if not is_owner else "admin"
    with pg_session() as pg:
        result = pg.execute(
            fr_sql.insert_feature_request(),
            {
                "title": title,
                "description": description,
                "username": current_user
            }
        ).fetchone()
       
        # Redirect to the new feature request page
        if result:
            new_id = result[0]
           
            # Post to Discord
            post_to_discord(
                webhook_type="feature_requests",
                title="💡 New Feature Request",
                description=f"**{title}**\n\n{description}",
                url=url_for("feature_requests.single_feature_request", request_id=new_id, _external=True),
                fields=[
                    {"name": "Submitted by", "value": display_name, "inline": True},
                    {"name": "Request ID", "value": f"#{new_id}", "inline": True}
                ],
                footer_text="Feature Requests"
            )
           
            return redirect(url_for("feature_requests.single_feature_request", request_id=new_id))
   
    return redirect(url_for("feature_requests.feature_requests"))


@feature_requests_blueprint.route("/<username>/feature_requests/edit", methods=["POST"])
@login_required
def edit_feature_request(username):
    """Edit a feature request (owner can edit any, users can edit their own)"""
    request_id = request.form["request_id"]
    title = request.form["title"]
    description = request.form["description"]
    current_user = session["userinfo"]["logged_in_user"]
    is_owner = session["userinfo"].get("is_owner", False)
    
    with pg_session() as pg:
        # Check if user can edit this request
        if not is_owner:
            # Regular user can only edit their own requests
            result = pg.execute(
                fr_sql.get_feature_request_author(),
                {"request_id": request_id}
            ).fetchone()
            
            if not result or result[0] != current_user:
                logger.warning(f"User {current_user} attempted to edit request {request_id} they don't own")
                return redirect(url_for("feature_requests.feature_requests"))
        
        # Update the request
        pg.execute(
            fr_sql.update_feature_request(),
            {
                "request_id": request_id,
                "title": title,
                "description": description
            }
        )
    
    return redirect(url_for("feature_requests.single_feature_request", request_id=request_id))


@feature_requests_blueprint.route("/<username>/feature_requests/delete", methods=["POST"])
@login_required
def delete_feature_request(username):
    """Delete a feature request (owner can delete any, users can delete their own)"""
    request_id = request.form["request_id"]
    current_user = session["userinfo"]["logged_in_user"]
    is_owner = session["userinfo"].get("is_owner", False)
    
    with pg_session() as pg:
        # Check if user can delete this request
        if not is_owner:
            # Regular user can only delete their own requests
            result = pg.execute(
                fr_sql.get_feature_request_author(),
                {"request_id": request_id}
            ).fetchone()
            
            if not result or result[0] != current_user:
                logger.warning(f"User {current_user} attempted to delete request {request_id} they don't own")
                return redirect(url_for("feature_requests.feature_requests"))
        
        # Delete associated votes first
        pg.execute(
            fr_sql.delete_all_votes_for_request(),
            {"request_id": request_id}
        )
        
        # Delete the request
        pg.execute(
            fr_sql.delete_feature_request(),
            {"request_id": request_id}
        )
    
    return redirect(url_for("feature_requests.feature_requests"))


@feature_requests_blueprint.route("/<username>/feature_requests/vote", methods=["POST"])
@login_required
def vote_feature_request(username):
    """Handle upvote/downvote for feature requests"""
    # Prevent owner from voting
    if session["userinfo"]["is_owner"]:
        return redirect(url_for("feature_requests.feature_requests"))
        
    request_id = request.form.get("request_id")
    vote_type = request.form.get("vote_type")
    current_user = session["userinfo"]["logged_in_user"]
    
    # Validate inputs
    if not request_id or not vote_type:
        logger.error(f"Missing request_id ({request_id}) or vote_type ({vote_type})")
        return redirect(url_for("feature_requests.feature_requests"))
    
    try:
        request_id = int(request_id)
    except (ValueError, TypeError):
        logger.error(f"Invalid request_id: {request_id}")
        return redirect(url_for("feature_requests.feature_requests"))
    
    if vote_type not in ['upvote', 'downvote']:
        logger.error(f"Invalid vote_type: {vote_type}")
        return redirect(url_for("feature_requests.feature_requests"))
    
    with pg_session() as pg:
        # Check if user has already voted on this request
        existing_vote_result = pg.execute(
            fr_sql.get_user_vote(),
            {"request_id": request_id, "username": current_user}
        ).fetchone()
        
        existing_vote = existing_vote_result[0] if existing_vote_result else None
        
        if existing_vote:
            if existing_vote == vote_type:
                # User is clicking the same vote - remove it
                pg.execute(
                    fr_sql.delete_vote(),
                    {"request_id": request_id, "username": current_user}
                )
            else:
                # User is changing their vote
                pg.execute(
                    fr_sql.update_vote(),
                    {
                        "request_id": request_id,
                        "username": current_user,
                        "vote_type": vote_type
                    }
                )
        else:
            # New vote
            pg.execute(
                fr_sql.insert_vote(),
                {
                    "request_id": request_id,
                    "username": current_user,
                    "vote_type": vote_type
                }
            )
        
        # Update vote counts in feature_requests table
        pg.execute(
            fr_sql.update_vote_counts(),
            {"request_id": request_id}
        )
    
    # Check if we came from single request page
    referer = request.headers.get('Referer', '')
    if f'/feature_requests/{request_id}' in referer:
        return redirect(url_for("feature_requests.single_feature_request", request_id=request_id))
    
    return redirect(url_for("feature_requests.feature_requests"))


@feature_requests_blueprint.route("/<username>/feature_requests/update_status", methods=["POST"])
@owner_required
def update_feature_request_status(username):
    """Update status of a feature request (owner only)"""
    request_id = request.form["request_id"]
    new_status = request.form["status"]
    
    with pg_session() as pg:
        pg.execute(
            fr_sql.update_feature_request_status(),
            {"request_id": request_id, "status": new_status}
        )
    
    # Check if we came from single request page
    referer = request.headers.get('Referer', '')
    if f'/feature_requests/{request_id}' in referer:
        return redirect(url_for("feature_requests.single_feature_request", request_id=request_id))
    
    return redirect(url_for("feature_requests.feature_requests"))


@feature_requests_blueprint.route("/feature_requests/<int:request_id>/voters")
def feature_request_voters(request_id):
    """Get list of voters for a feature request"""
    with pg_session() as pg:
        result = pg.execute(
            fr_sql.list_voters(),
            {"request_id": request_id}
        ).fetchall()
        
        voters = {
            'upvoters': [],
            'downvoters': []
        }
        
        for vote in result:
            vote_data = {
                'username': vote[0],
                'created': vote[2].isoformat() if vote[2] else None
            }
            
            if vote[1] == 'upvote':
                voters['upvoters'].append(vote_data)
            else:
                voters['downvoters'].append(vote_data)
    
    return jsonify(voters)


@feature_requests_blueprint.route("/feature_requests/<int:request_id>/voters")
def public_feature_request_voters(request_id):
    """Get list of voters for a feature request (public route)"""
    with pg_session() as pg:
        result = pg.execute(
            fr_sql.list_voters(),
            {"request_id": request_id}
        ).fetchall()
        
        voters = {
            'upvoters': [],
            'downvoters': []
        }
        
        for vote in result:
            vote_data = {
                'username': vote[0],
                'created': vote[2].isoformat() if vote[2] else None
            }
            
            if vote[1] == 'upvote':
                voters['upvoters'].append(vote_data)
            else:
                voters['downvoters'].append(vote_data)
    
    return jsonify(voters)


@feature_requests_blueprint.route("/feature_requests/<int:request_id>/details")
def get_feature_request_details(request_id):
    """Get feature request details for editing"""
    with pg_session() as pg:
        result = pg.execute(
            fr_sql.get_feature_request_details(),
            {"request_id": request_id}
        ).fetchone()
        
        if result:
            return jsonify({
                'id': result[0],
                'title': result[1],
                'description': result[2],
                'author': result[3]
            })
        else:
            return jsonify({'error': 'Feature request not found'}), 404