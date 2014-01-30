from django.http import HttpResponse,Http404,HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.shortcuts import render_to_response
from django.template import RequestContext,Context
from django.template.loader import get_template
from django.conf import settings
from django import forms
from django.forms.util import ErrorList
from models import *
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import subqueryload,subqueryload_all
from sqlalchemy.orm import joinedload,joinedload_all
from sqlalchemy.orm import undefer
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import desc
from sqlalchemy.sql.expression import tuple_,func,null
from sqlalchemy import distinct
from quicktill.models import *

# We use this date format in templates - defined here so we don't have
# to keep repeating it.  It's available in templates as 'dtf'
dtf="Y-m-d H:i"

# This view is only used when the tillweb is integrated into another
# django-based website.
@login_required
def publist(request):
    access=Access.objects.filter(user=request.user)
    return render_to_response('tillweb/publist.html',
                              {'access':access,},
                              context_instance=RequestContext(request))

# The remainder of the view functions in this file follow a similar
# pattern.  They are kept separate rather than implemented as a
# generic view so that page-specific optimisations (the ".options()"
# clauses in the queries) can be added.  The common operations have
# been moved into the @tillweb_view decorator.

# This app can be deployed in one of two ways:

# 1. Integrated into a complete django-based website, with its own
# users and access controls.  In this case, information about which
# database to connect to and what users are permitted to do is fetched
# from the Till and Access models.  This case is used when the
# TILLWEB_SINGLE_SITE setting is absent or False.

# 2. As a standalone website, possibly with no concept of users and
# access controls.  In this case, the database, pubname and default
# access permission are read from the rest of the TILLWEB_ settings.

# Views are passed the following parameters:
# request - the Django http request object
# base - the base URL for the till's website
# user - the quicktill.models.User object if available, or 'R','M','F'
# session - sqlalchemy database session

def tillweb_view(view):
    single_site=getattr(settings,'TILLWEB_SINGLE_SITE',False)
    def new_view(request,pubname,*args,**kwargs):
        if single_site:
            tillname=settings.TILLWEB_PUBNAME
            access=settings.TILLWEB_DEFAULT_ACCESS
            session=settings.TILLWEB_DATABASE()
            base='/'
        else:
            try:
                till=Till.objects.get(slug=pubname)
            except Till.DoesNotExist:
                raise Http404
            try:
                access=Access.objects.get(user=request.user,till=till)
            except Access.DoesNotExist:
                # Pretend it doesn't exist!
                raise Http404
            try:
                session=settings.SQLALCHEMY_SESSIONS[till.database]()
            except ValueError:
                # The database doesn't exist
                raise Http404
            base=till.get_absolute_url()
            tillname=till.name
            access=access.permission
        try:
            depts=session.query(Department).order_by(Department.id).all()
            result=view(request,base,access,session,*args,**kwargs)
            if isinstance(result,HttpResponse): return result
            t,d=result
            # object is the Till object, possibly used for a nav menu
            # (it's None if we are set up for a single site)
            # till is the name of the till
            # access is 'R','M','F'
            # u is the base URL for the till website including trailing /
            defaults={'object':None if settings.TILLWEB_SINGLE_SITE else till,
                      'till':tillname,'access':access,'u':base,
                      'depts':depts,'dtf':dtf}
            defaults.update(d)
            return render_to_response(
                'tillweb/'+t,defaults,
                context_instance=RequestContext(request))
        except OperationalError as oe:
            t=get_template('tillweb/operationalerror.html')
            return HttpResponse(
                t.render(RequestContext(
                        request,{'object':till,'access':access,'error':oe})),
                status=503)
        finally:
            session.close()
    if single_site and settings.TILLWEB_LOGIN_REQUIRED:
        new_view=login_required(new_view)
    return new_view

def business_totals(session,firstday,lastday):
    # This query is wrong in that it ignores the 'business' field in
    # VatRate objects.  Fixes that don't involve a database round-trip
    # per session are welcome!
    return session.query(Business,func.sum(Transline.items*Transline.amount)).\
        join(VatBand).\
        join(Department).\
        join(Transline).\
        join(Transaction).\
        join(Session).\
        filter(Session.date<=lastday).\
        filter(Session.date>=firstday).\
        group_by(Business).\
        all()

@tillweb_view
def pubroot(request,base,access,session):
    date=datetime.date.today()
    # If it's the early hours of the morning, it's more useful for us
    # to consider it still to be yesterday.
    if datetime.datetime.now().hour<4: date=date-datetime.timedelta(1)
    thisweek_start=date-datetime.timedelta(date.weekday())
    thisweek_end=thisweek_start+datetime.timedelta(6)
    lastweek_start=thisweek_start-datetime.timedelta(7)
    lastweek_end=thisweek_end-datetime.timedelta(7)
    weekbefore_start=lastweek_start-datetime.timedelta(7)
    weekbefore_end=lastweek_end-datetime.timedelta(7)

    weeks=[("Current week",thisweek_start,thisweek_end,
            business_totals(session,thisweek_start,thisweek_end)),
           ("Last week",lastweek_start,lastweek_end,
            business_totals(session,lastweek_start,lastweek_end)),
           ("The week before last",weekbefore_start,weekbefore_end,
            business_totals(session,weekbefore_start,weekbefore_end))]

    currentsession=Session.current(session)
    barsummary=session.query(StockLine).\
        filter(StockLine.location=="Bar").\
        order_by(StockLine.dept_id,StockLine.name).\
        options(joinedload_all('stockonsale.stocktype.unit')).\
        all()
    stillage=session.query(StockAnnotation).\
        join(StockItem).\
        outerjoin(StockLine).\
        filter(tuple_(StockAnnotation.text,StockAnnotation.time).in_(
            select([StockAnnotation.text,func.max(StockAnnotation.time)],
                   StockAnnotation.atype=='location').\
                group_by(StockAnnotation.text))).\
        filter(StockItem.finished==None).\
        order_by(StockLine.name!=null(),StockAnnotation.time).\
        options(joinedload_all('stockitem.stocktype.unit')).\
        options(joinedload_all('stockitem.stockline')).\
        all()
    return ('index.html',
            {'currentsession':currentsession,
             'barsummary':barsummary,
             'stillage':stillage,
             'weeks':weeks,
             })

@tillweb_view
def locationlist(request,base,access,session):
    locations=[x[0] for x in session.query(distinct(StockLine.location)).\
                   order_by(StockLine.location).all()]
    return ('locations.html',{'locations':locations})

@tillweb_view
def location(request,base,access,session,location):
    lines=session.query(StockLine).\
        filter(StockLine.location==location).\
        order_by(StockLine.dept_id,StockLine.name).\
        options(joinedload('stockonsale')).\
        options(joinedload('stockonsale.stocktype')).\
        all()
    return ('location.html',{'location':location,'lines':lines})

class SessionFinderForm(forms.Form):
    session=forms.IntegerField(label="Session ID")

@tillweb_view
def sessionfinder(request,base,access,session):
    if request.method=='POST':
        form=SessionFinderForm(request.POST)
        if form.is_valid():
            s=session.query(Session).get(form.cleaned_data['session'])
            if s:
                return HttpResponseRedirect(base+s.tillweb_url)
            errors=form._errors.setdefault("session",ErrorList())
            errors.append(u"This session does not exist.")
    else:
        form=SessionFinderForm()
    recent=session.query(Session).\
        options(undefer('total')).\
        options(undefer('actual_total')).\
        order_by(desc(Session.id))[:30]
    return ('sessions.html',{'recent':recent,'form':form})

@tillweb_view
def session(request,base,access,session,sessionid):
    try:
        # The subqueryload_all() significantly improves the speed of loading
        # the transaction totals
        s=session.query(Session).\
            filter_by(id=int(sessionid)).\
            options(subqueryload_all('transactions.lines')).\
            one()
    except NoResultFound:
        raise Http404
    nextsession=session.query(Session).\
        filter(Session.id>s.id).\
        order_by(Session.id).\
        first()
    nextlink=base+nextsession.tillweb_url if nextsession else None
    prevsession=session.query(Session).\
        filter(Session.id<s.id).\
        order_by(desc(Session.id)).\
        first()
    prevlink=base+prevsession.tillweb_url if prevsession else None
    return ('session.html',{'session':s,'nextlink':nextlink,
                            'prevlink':prevlink})

@tillweb_view
def sessiondept(request,base,access,session,sessionid,dept):
    try:
        s=session.query(Session).filter_by(id=int(sessionid)).one()
    except NoResultFound:
        raise Http404
    try:
        dept=session.query(Department).filter_by(id=int(dept)).one()
    except NoResultFound:
        raise Http404
    nextsession=session.query(Session).\
        filter(Session.id>s.id).\
        order_by(Session.id).\
        first()
    nextlink=base+nextsession.tillweb_url+"dept{}/".format(dept.id) \
        if nextsession else None
    prevsession=session.query(Session).\
        filter(Session.id<s.id).\
        order_by(desc(Session.id)).\
        first()
    prevlink=base+prevsession.tillweb_url+"dept{}/".format(dept.id) \
        if prevsession else None
    translines=session.query(Transline).\
        join(Transaction).\
        options(joinedload('transaction')).\
        options(joinedload('user')).\
        options(joinedload_all('stockref.stockitem.stocktype.unit')).\
        filter(Transaction.sessionid==s.id).\
        filter(Transline.dept_id==dept.id).\
        order_by(Transline.id).\
        all()
    return ('sessiondept.html',{'session':s,'department':dept,
                                'translines':translines,
                                'nextlink':nextlink,'prevlink':prevlink})

@tillweb_view
def transaction(request,base,access,session,transid):
    try:
        t=session.query(Transaction).\
            filter_by(id=int(transid)).\
            options(subqueryload_all('payments')).\
            options(joinedload_all('lines.stockref.stockitem.stocktype')).\
            one()
    except NoResultFound:
        raise Http404
    return ('transaction.html',{'transaction':t,})

@tillweb_view
def supplierlist(request,base,access,session):
    sl=session.query(Supplier).order_by(Supplier.name).all()
    return ('suppliers.html',{'suppliers':sl})

@tillweb_view
def supplier(request,base,access,session,supplierid):
    try:
        s=session.query(Supplier).\
            filter_by(id=int(supplierid)).\
            one()
    except NoResultFound:
        raise Http404
    return ('supplier.html',{'supplier':s,})

@tillweb_view
def deliverylist(request,base,access,session):
    dl=session.query(Delivery).order_by(desc(Delivery.id)).\
        options(joinedload('supplier')).\
        all()
    return ('deliveries.html',{'deliveries':dl})

@tillweb_view
def delivery(request,base,access,session,deliveryid):
    try:
        d=session.query(Delivery).\
            filter_by(id=int(deliveryid)).\
            one()
    except NoResultFound:
        raise Http404
    return ('delivery.html',{'delivery':d,})

class StockTypeForm(forms.Form):
    manufacturer=forms.CharField(required=False)
    name=forms.CharField(required=False)
    shortname=forms.CharField(required=False)
    def is_filled_in(self):
        cd=self.cleaned_data
        return cd['manufacturer'] or cd['name'] or cd['shortname']
    def filter(self,q):
        cd=self.cleaned_data
        if cd['manufacturer']:
            q=q.filter(StockType.manufacturer.ilike("%{}%".format(cd['manufacturer'])))
        if cd['name']:
            q=q.filter(StockType.name.ilike("%{}%".format(cd['name'])))
        if cd['shortname']:
            q=q.filter(StockType.shortname.ilike("%{}%".format(cd['shortname'])))
        return q

@tillweb_view
def stocktypesearch(request,base,access,session):
    form=StockTypeForm(request.GET)
    result=[]
    q=session.query(StockType).order_by(
        StockType.dept_id,StockType.manufacturer,StockType.name)
    if form.is_valid():
        if form.is_filled_in():
            q=form.filter(q)
            result=q.all()
    return ('stocktypesearch.html',{'form':form,'stocktypes':result})

@tillweb_view
def stocktype(request,base,access,session,stocktype_id):
    try:
        s=session.query(StockType).\
            filter_by(id=int(stocktype_id)).\
            one()
    except NoResultFound:
        raise Http404
    include_finished=request.GET.get("show_finished","off")=="on"
    items=session.query(StockItem).\
        filter(StockItem.stocktype==s).\
        order_by(desc(StockItem.id))
    if not include_finished:
        items=items.filter(StockItem.finished==None)
    items=items.all()
    return ('stocktype.html',{'stocktype':s,'items':items,
                              'include_finished':include_finished})

class StockForm(StockTypeForm):
    include_finished=forms.BooleanField(
        required=False,label="Include finished items")

@tillweb_view
def stocksearch(request,base,access,session):
    form=StockForm(request.GET)
    result=[]
    q=session.query(StockItem).join(StockType).order_by(StockItem.id).\
        options(joinedload_all('stocktype.unit')).\
        options(joinedload('stockline')).\
        options(undefer('used')).\
        options(undefer('sold')).\
        options(undefer('remaining'))
    if form.is_valid():
        if form.is_filled_in():
            q=form.filter(q)
            if not form.cleaned_data['include_finished']:
                q=q.filter(StockItem.finished==None)
            result=q.all()
    return ('stocksearch.html',{'form':form,'stocklist':result})

@tillweb_view
def stock(request,base,access,session,stockid):
    try:
        s=session.query(StockItem).\
            filter_by(id=int(stockid)).\
            options(joinedload('stocktype')).\
            options(joinedload('stocktype.department')).\
            options(joinedload('stocktype.stockline_log')).\
            options(joinedload('stocktype.stockline_log.stockline')).\
            options(joinedload('delivery')).\
            options(joinedload('delivery.supplier')).\
            options(joinedload('stockunit')).\
            options(joinedload('stockunit.unit')).\
            options(subqueryload_all('out.transline.transaction')).\
            one()
    except NoResultFound:
        raise Http404
    return ('stock.html',{'stock':s,})

@tillweb_view
def stocklinelist(request,base,access,session):
    lines=session.query(StockLine).\
        order_by(StockLine.dept_id,StockLine.name).\
        all()
    return ('stocklines.html',{'lines':lines,})

@tillweb_view
def stockline(request,base,access,session,stocklineid):
    try:
        s=session.query(StockLine).\
            filter_by(id=int(stocklineid)).\
            one()
    except NoResultFound:
        raise Http404
    return ('stockline.html',{'stockline':s,})

@tillweb_view
def departmentlist(request,base,access,session):
    # depts are included in template context anyway
    return ('departmentlist.html',{})

@tillweb_view
def department(request,base,access,session,departmentid):
    d=session.query(Department).get(int(departmentid))
    if d is None: raise Http404
    include_finished=request.GET.get("show_finished","off")=="on"
    items=session.query(StockItem).\
        join(StockType).\
        filter(StockType.department==d).\
        order_by(desc(StockItem.id)).\
        options(joinedload_all('stocktype.unit')).\
        options(undefer('used')).\
        options(undefer('sold')).\
        options(undefer('remaining')).\
        options(joinedload('stockline')).\
        options(joinedload('finishcode'))
    if not include_finished:
        items=items.filter(StockItem.finished==None)
    items=items.all()
    return ('department.html',{'department':d,'items':items,
                               'include_finished':include_finished})

@tillweb_view
def userlist(request,base,access,session):
    q=session.query(User).order_by(User.fullname)
    include_inactive=request.GET.get("include_inactive","off")=="on"
    if not include_inactive:
        q=q.filter(User.enabled==True)
    users=q.all()
    return ('userlist.html',{'users':users,'include_inactive':include_inactive})

@tillweb_view
def user(request,base,access,session,userid):
    try:
        u=session.query(User).\
            options(joinedload('permissions')).\
            options(joinedload('tokens')).\
            get(int(userid))
    except NoResultFound:
        raise Http404
    sales=session.query(Transline).filter(Transline.user==u).\
        options(joinedload('transaction')).\
        options(joinedload_all('stockref.stockitem.stocktype.unit')).\
        order_by(desc(Transline.time))[:50]
    payments=session.query(Payment).filter(Payment.user==u).\
        options(joinedload('transaction')).\
        options(joinedload('paytype')).\
        order_by(desc(Payment.time))[:50]
    annotations=session.query(StockAnnotation).\
        options(joinedload_all('stockitem.stocktype')).\
        options(joinedload('type')).\
        filter(StockAnnotation.user==u).\
        order_by(desc(StockAnnotation.time))[:50]
    return ('user.html',{'user':u,'sales':sales,'payments':payments,
                         'annotations':annotations})
