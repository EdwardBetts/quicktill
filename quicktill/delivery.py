from . import ui, stock, td, keyboard, printer, tillconfig, stocktype
from . import user, usestock
from decimal import Decimal
from .models import Delivery, Supplier, StockUnit, StockItem, StockType
from .models import penny
from .plugins import InstancePluginMount
import datetime
from sqlalchemy.exc import IntegrityError

import logging
log = logging.getLogger(__name__)

@user.permission_required('deliveries', "List deliveries")
def deliverymenu():
    """Display a list of deliveries and call the edit function.
    """
    dl = td.s.query(Delivery)\
             .order_by(Delivery.checked)\
             .order_by(Delivery.date.desc())\
             .order_by(Delivery.id.desc())\
             .all()
    f = ui.tableformatter(' r L l L l ')
    lines = [(f(x.id, x.supplier.name, x.date, x.docnumber or "",
                "" if x.checked else "not confirmed"),
              delivery, (x.id,)) for x in dl]
    lines.insert(0, ("Record new delivery", delivery, None))
    ui.menu(lines, title="Delivery List",
            blurb="Select a delivery and press Cash/Enter.")

class deliveryline(ui.line):
    def __init__(self, stockitem):
        ui.line.__init__(self)
        self.stockitem = stockitem
        self.update()

    def update(self):
        s = self.stockitem
        td.s.add(s)
        try:
            coststr = format(s.costprice, ">-6.2f")
        except:
            coststr = "??????"
        try:
            salestr = format(s.stocktype.saleprice, ">-5.2f")
        except:
            salestr = "?????"
        self.text = "{:>7} {:<37} {:<8} {} {} {:10}".format(
            s.id, s.stocktype.format(maxw=37), s.description[:8],
            coststr, salestr, ui.formatdate(s.bestbefore))

class delivery(ui.basicpopup):
    """Delivery popup

    The delivery window allows a delivery to be edited, printed or
    confirmed.  Prior to confirmation all details of a delivery can be
    changed.  After confirmation the delivery is read-only.  The
    window contains a header area, with supplier name, delivery date
    and document number; a couple of prompts, and a scrollable list of
    stock items.  If the window is not read-only, there is always a
    blank line at the bottom of the list to enable new entries to be
    made.

    If no delivery ID is passed, a new delivery will be created once a
    supplier has been chosen.
    """
    def __init__(self, dn=None):
        mh, mw = ui.rootwin.size()
        if mw < 80 or mh < 14:
            ui.infopopup(["Error: the screen is too small to display "
                          "the delivery dialog box.  It must be at least "
                          "80x14 characters."],
                         title="Screen width problem")
            return
        if dn:
            d = td.s.query(Delivery).get(dn)
        else:
            d = None
        if d:
            self.dl = [deliveryline(x) for x in d.items]
            self.dn = d.id
        else:
            self.dl = []
            self.dn = None
        if d and d.checked:
            title = "Delivery Details - %d - read only (already confirmed)" % d.id
            cleartext = "Press Clear to go back"
            skm = {keyboard.K_CASH: (self.view_line, None)}
            readonly = True
        else:
            title = "Delivery Details"
            if self.dn:
                title = title + " - %d" % self.dn
            cleartext = None
            skm = {keyboard.K_CASH: (self.edit_line, None),
                   keyboard.K_CANCEL: (self.deleteline, None),
                   keyboard.K_QUANTITY: (self.duplicate_item, None)}
            readonly = False
        # The window can be as tall as the screen; we expand the scrollable
        # field to fit.  The scrollable field must be at least three lines
        # high!
        ui.basicpopup.__init__(
            self, mh, 80, title=title, cleartext=cleartext,
            colour=ui.colour_input)
        if readonly:
            self.win.set_cursor(False)
        self.addstr(2, 2, "       Supplier:")
        self.addstr(3, 2, "           Date:")
        self.addstr(4, 2, "Document number:")
        self.addstr(6, 1, "StockNo Stock Type........................... "
                    "Unit.... Cost.. Sale  BestBefore")
        self.supfield = ui.modelfield(
            2, 19, 59, Supplier, 'name', default=d.supplier if d else None,
            create=createsupplier, readonly=readonly)
        # If there is not yet an underlying Delivery object, the window
        # can be dismissed by pressing Clear on the supplier field
        if self.dn is None:
            self.supfield.keymap[keyboard.K_CLEAR] = (self.dismiss, None)
        self.datefield = ui.datefield(
            3, 19, f=d.date if d else datetime.date.today(),
            readonly=readonly)
        self.docnumfield = ui.editfield(4, 19, 40, f=d.docnumber if d else "",
                                        readonly=readonly)
        self.entryprompt = None if readonly else ui.line(
            " [ New item ]")
        self.s = ui.scrollable(
            7, 1, 78, mh - 9 if readonly else mh - 10, self.dl,
            lastline=self.entryprompt, keymap=skm)
        self.addstr(mh - 2 if readonly else mh - 3, 33, "Total cost ex-VAT:")
        self.costfield = ui.label(mh - 2 if readonly else mh - 3,
                                  52, 10, align='>')
        self.update_costfield()
        if readonly:
            self.s.focus()
        else:
            self.deletefield = ui.buttonfield(
                mh - 2, 2, 24, "Delete this delivery", keymap={
                    keyboard.K_CASH: (self.confirmdelete, None)})
            self.confirmfield = ui.buttonfield(
                mh - 2, 28, 31, "Confirm details are correct", keymap={
                    keyboard.K_CASH: (self.confirmcheck, None)})
            self.savefield = ui.buttonfield(
                mh - 2, 61, 17, "Save and exit", keymap={
                    keyboard.K_CASH: (self.finish, None)})
            ui.map_fieldlist(
                [self.supfield, self.datefield, self.docnumfield, self.s,
                 self.deletefield, self.confirmfield, self.savefield])
            self.supfield.sethook = self.update_model
            self.datefield.sethook = self.update_model
            self.docnumfield.sethook = self.update_model
            if self.dn:
                self.s.focus()
            else:
                self.supfield.focus()

    def update_costfield(self):
        if self.dn:
            d = td.s.query(Delivery).get(self.dn)
            self.costfield.set(
                tillconfig.fc(d.costprice) if d.costprice else "??????")

    def update_model(self):
        # Called whenever one of the three fields at the top changes.
        # If the three fields are valid and we have a Delivery model,
        # update it.  If any of them are not valid, or there is not
        # yet a Delivery model, do nothing.
        if self.supfield.f is None:
            return
        date = self.datefield.read()
        if not date:
            return
        if self.docnumfield.f == "":
            return
        if not self.dn:
            return
        d = td.s.query(Delivery).get(self.dn)
        d.supplier = self.supfield.read()
        d.date = date
        d.docnumber = self.docnumfield.f
        td.s.flush()
        self.update_costfield()

    def make_delivery_model(self):
        # If we do not have a delivery ID, create one if possible.  If
        # we still don't have one after this, it's because a required
        # field was missing and we've just popped up an error message
        # about it.
        if self.dn:
            return
        if self.supfield.f is None:
            ui.infopopup(["Select a supplier before continuing!"], title="Error")
            return
        date = self.datefield.read()
        if date is None:
            ui.infopopup(["Check that the delivery date is correct before "
                          "continuing!"], title="Error")
            return
        if self.docnumfield.f == "":
            ui.infopopup(["Enter a document number before continuing!"],
                         title="Error")
            return
        d = Delivery()
        d.supplier = self.supfield.read()
        d.date = date
        d.docnumber = self.docnumfield.f
        td.s.add(d)
        td.s.flush()
        self.dn = d.id
        del self.supfield.keymap[keyboard.K_CLEAR]
        self.addstr(0, 1, "Delivery Details - {}".format(d.id))

    def finish(self):
        # Save and exit button
        self.make_delivery_model()
        if self.dn:
            self.dismiss()

    def reallydeleteline(self):
        item = self.dl[self.s.cursor].stockitem
        td.s.add(item)
        td.s.delete(item)
        del self.dl[self.s.cursor]
        td.s.flush()
        self.s.drawdl()
        self.update_costfield()

    def deleteline(self):
        if not self.s.cursor_on_lastline():
            td.s.add(self.dl[self.s.cursor].stockitem)
            ui.infopopup(
                ["Press Cash/Enter to confirm deletion of stock "
                 "number %d.  Note that once it's deleted you can't "
                 "create a new stock item with the same number; new "
                 "stock items always get fresh numbers." % (
                        self.dl[self.s.cursor].stockitem.id)],
                title="Confirm Delete",
                keymap={keyboard.K_CASH: (self.reallydeleteline, None, True)})

    def printout(self):
        if self.dn is None:
            return
        menu = [("Print labels on {}".format(str(x)),
                 printer.label_print_delivery,(x,self.dn))
                for x in printer.labelprinters]
        ui.automenu(menu, title="Delivery print options",
                    colour=ui.colour_confirm)

    def reallyconfirm(self):
        if not self.dn:
            return
        d = td.s.query(Delivery).get(self.dn)
        d.checked = True
        td.s.flush()
        self.dismiss()
        usestock.auto_allocate_internal(deliveryid=self.dn,
                                        message_on_no_work=False)
        for i in DeliveryHooks.instances:
            i.confirmed(self.dn)

    def confirmcheck(self):
        if not self.dn or not self.dl:
            ui.infopopup(["There is nothing here to confirm!"],
                         title="Error")
            return
        for i in DeliveryHooks.instances:
            if i.preConfirm(self.dn):
                return
        ui.infopopup(["When you confirm a delivery you are asserting that "
                      "you have received and checked every item listed as part "
                      "of the delivery.  Once the delivery is confirmed, you "
                      "can't go back and change any of the details.  Press "
                      "Cash/Enter to confirm this delivery now, or Clear to "
                      "continue editing it."], title="Confirm Details",
                     keymap={keyboard.K_CASH: (self.reallyconfirm, None, True)})

    def line_edited(self, stockitem):
        # Only called when a line has been edited; not called for new
        # lines or deletions
        self.dl[self.s.cursor].update()
        self.s.cursor_down()
        self.update_costfield()

    def newline(self, stockitem):
        self.dl.append(deliveryline(stockitem))
        self.s.cursor_down()
        self.update_costfield()

    def edit_line(self):
        # If there is not yet an underlying Delivery object, create one
        self.make_delivery_model()
        if self.dn is None:
            return # with errors already popped up
        # If it's the "lastline" then we create a new stock item
        if self.s.cursor_on_lastline():
            new_stockitem(self.newline, self.dn)
        else:
            td.s.add(self.dl[self.s.cursor].stockitem)
            edit_stockitem(self.line_edited, self.dn,
                           self.dl[self.s.cursor].stockitem)

    def view_line(self):
        # In read-only mode there is no "lastline"
        td.s.add(self.dl[self.s.cursor].stockitem)
        stock.stockinfo_popup(self.dl[self.s.cursor].stockitem.id)

    def duplicate_item(self):
        existing = self.dl[len(self.dl) - 1 if self.s.cursor_on_lastline()
                           else self.s.cursor].stockitem
        td.s.add(existing)
        # We deliberately do not copy the best-before date, because it
        # might be different on the new item.
        new = StockItem(
            delivery=existing.delivery, stocktype=existing.stocktype,
            description=existing.description, size=existing.size,
            costprice=existing.costprice)
        td.s.add(new)
        td.s.flush()
        self.dl.append(deliveryline(new))
        self.s.cursor_down()
        self.update_costfield()

    def reallydelete(self):
        if self.dn is None:
            self.dismiss()
            return
        d = td.s.query(Delivery).get(self.dn)
        for i in d.items:
            td.s.delete(i)
        td.s.delete(d)
        self.dismiss()

    def confirmdelete(self):
        ui.infopopup(["Do you want to delete the entire delivery and all "
                      "the stock items that have been entered for it?  "
                      "Press Cancel to delete or Clear to go back."],
                     title="Confirm Delete",
                     keymap={keyboard.K_CANCEL: (self.reallydelete, None, True)})

    def keypress(self, k):
        if k == keyboard.K_PRINT:
            self.printout()
        elif k == keyboard.K_CLEAR:
            self.dismiss()

class new_stockitem(ui.basicpopup):
    """Create a number of stockitems."""

    @staticmethod
    def _null_list(query):
        return query.filter(False)

    def __init__(self, func, deliveryid):
        """Create one or more StockItems and call func with the StockItem as
        an argument (possibly multiple times).  The StockItem we call
        func with is in the current ORM session.
        """
        self.func = func
        self.deliveryid = deliveryid
        cleartext = "Press Clear to exit without creating a new stock item"
        ui.basicpopup.__init__(self, 13, 78, title="Stock Item",
                               cleartext=cleartext, colour=ui.colour_line)
        self.addstr(2, 2, "          Stock type:")
        self.addstr(3, 2, "           Item size:")
        self.addstr(4, 2, "     Number of items:")
        self.addstr(5, 2, " Cost price (ex VAT): {}".format(tillconfig.currency))
        self.addstr(6, 2, "Suggested sale price:")
        self.addstr(7, 2, "Sale price (inc VAT): {}".format(tillconfig.currency))
        self.addstr(7, 31 + len(tillconfig.currency), "per")
        self.addstr(8, 2, "         Best before:")
        self.typefield = ui.modelpopupfield(
            2, 24, 52, StockType, stocktype.choose_stocktype,
            lambda si: si.format(),
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.typefield.sethook = self.typefield_changed
        self.unitfield = ui.modellistfield(
            3, 24, 30, StockUnit, self._null_list, lambda x: x.name)
        self.unitfield.sethook = self.update_suggested_price
        self.qtyfield = ui.editfield(
            4, 24, 5, f=1,
            validate=ui.validate_positive_nonzero_int)
        self.qtyfield.sethook = self.update_suggested_price
        self.costfield = ui.editfield(5, 24 + len(tillconfig.currency), 10,
                                      validate=ui.validate_float)
        self.costfield.sethook = self.update_suggested_price
        self.suggested_price = ui.label(6, 24, 77 - 24)
        self.salefield = ui.editfield(7, 24 + len(tillconfig.currency), 6,
                                      validate=ui.validate_float)
        self.saleunits = ui.label(7, 35 + len(tillconfig.currency),
                                  77 - 35 - len(tillconfig.currency))
        self.bestbeforefield = ui.datefield(8, 24)
        self.acceptbutton = ui.buttonfield(10, 28, 21, "Accept values", keymap={
                keyboard.K_CASH: (self.accept, None)})
        fieldlist = [self.typefield, self.unitfield, self.qtyfield,
                     self.costfield, self.salefield, self.bestbeforefield,
                     self.acceptbutton]
        ui.map_fieldlist(fieldlist)
        self.typefield.focus()

    def typefield_changed(self):
        stocktype = self.typefield.read()
        if stocktype == None:
            self.unitfield.change_query(self._null_list)
            self.saleunits.set("")
            return
        unit_id = stocktype.unit.id
        def unit_list(query):
            return query.filter(StockUnit.unit_id == unit_id)\
                        .order_by(StockUnit.size)
        self.unitfield.change_query(unit_list)
        self.update_suggested_price()
        self.saleunits.set(stocktype.unit.item_name)
        self.salefield.set(stocktype.saleprice)

    def update_suggested_price(self):
        st = self.typefield.read()
        su = self.unitfield.read()
        cost = self.costfield.f
        qty = self.qtyfield.f
        if st is None or su is None or len(cost) == 0 or len(qty) == 0:
            self.suggested_price.set("")
            return
        qty = int(self.qtyfield.f)
        wholeprice = Decimal(self.costfield.f)
        g = stocktype.PriceGuessHook.guess_price(st, su, wholeprice / qty)
        if g is None:
            self.suggested_price.set("")
        else:
            if isinstance(g, Decimal):
                g = g.quantize(penny)
                self.suggested_price.set("{} per {}".format(
                    tillconfig.fc(g), st.unit.item_name))
            else:
                self.suggested_price.set(g)

    def accept(self):
        if len(self.qtyfield.f) == 0 \
           or self.typefield.read() is None \
           or self.unitfield.read() is None \
           or len(self.salefield.f) == 0:
            ui.infopopup(["You have not filled in all the fields.  "
                          "The only optional fields are 'Best Before' "
                          "and 'Cost Price'."],
                         title="Error")
            return
        self.dismiss()
        if len(self.costfield.f) == 0:
            cost = None
        else:
            cost = Decimal(self.costfield.f).quantize(penny)
        saleprice = Decimal(self.salefield.f).quantize(penny)
        stocktype = self.typefield.read()
        stockunit = self.unitfield.read()
        bestbefore = self.bestbeforefield.read()
        if stocktype.saleprice != saleprice:
            stocktype.saleprice = saleprice
            stocktype.pricechanged = datetime.datetime.now()
        qty = int(self.qtyfield.f)
        delivery = td.s.query(Delivery).get(self.deliveryid)
        items = delivery.add_items(stocktype, stockunit, qty, cost, bestbefore)
        td.s.flush()
        for item in items:
            self.func(item)

class edit_stockitem(ui.basicpopup):
    """Edit a single stockitem."""

    @staticmethod
    def _null_list(query):
        return query.filter(False)

    def __init__(self, func, deliveryid, item):
        self.func = func
        self.item = item
        self.deliveryid = deliveryid
        cleartext = "Press Clear to exit, forgetting all changes"
        ui.basicpopup.__init__(self, 13, 78,
                               title="Stock Item {}".format(item.id),
                               cleartext=cleartext, colour=ui.colour_line)
        self.addstr(2, 2, "          Stock type:")
        self.addstr(3, 2, "           Item size:")
        self.addstr(5, 2, " Cost price (ex VAT): {}".format(tillconfig.currency))
        self.addstr(6, 2, "Suggested sale price:")
        self.addstr(7, 2, "Sale price (inc VAT): {}".format(tillconfig.currency))
        self.addstr(7, 31 + len(tillconfig.currency), "per")
        self.addstr(8, 2, "         Best before:")
        self.typefield = ui.modelpopupfield(
            2, 24, 52, StockType, stocktype.choose_stocktype,
            lambda si: si.format(),
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.typefield.sethook = self.typefield_changed
        self.unitfield = ui.modellistfield(
            3, 24, 52, StockUnit, self._null_list, lambda x: x.name)
        self.unitfield.sethook = self.unitfield_changed
        self.description = ui.label(4, 24, 77 - 24)
        self.costfield = ui.editfield(5, 24 + len(tillconfig.currency), 10,
                                      validate=ui.validate_float)
        self.costfield.sethook = self.update_suggested_price
        self.suggested_price = ui.label(6, 24, 77 - 24)
        self.salefield = ui.editfield(7, 24 + len(tillconfig.currency), 6,
                                      validate=ui.validate_float)
        self.saleunits = ui.label(7, 35 + len(tillconfig.currency),
                                  77 - 35 - len(tillconfig.currency))
        self.bestbeforefield = ui.datefield(8, 24)
        self.acceptbutton = ui.buttonfield(10, 28, 21, "Accept values", keymap={
                keyboard.K_CASH: (self.accept, None)})
        fieldlist = [self.typefield, self.unitfield, self.costfield,
                     self.salefield, self.bestbeforefield, self.acceptbutton]
        ui.map_fieldlist(fieldlist)
        self.typefield.set(item.stocktype)
        # See if any stockunits match the item's current description and size
        u = td.s.query(StockUnit)\
                .filter(StockUnit.unit == item.stocktype.unit)\
                .filter(StockUnit.name == item.description)\
                .filter(StockUnit.size == item.size)\
                .first()
        self.unitfield.set(u)
        self.costfield.set(item.costprice)
        self.salefield.set(item.stocktype.saleprice)
        self.bestbeforefield.set(item.bestbefore)
        if self.bestbeforefield.f == "":
            self.bestbeforefield.focus()
        else:
            self.acceptbutton.focus()

    def typefield_changed(self):
        stocktype = self.typefield.read()
        if stocktype == None:
            self.unitfield.change_query(self._null_list)
            self.saleunits.set("")
            return
        unit_id = stocktype.unit.id
        def unit_list(query):
            return query.filter(StockUnit.unit_id == unit_id)\
                        .order_by(StockUnit.size)
        self.unitfield.change_query(unit_list)
        self.update_suggested_price()
        self.saleunits.set(stocktype.unit.item_name)
        self.salefield.set(stocktype.saleprice)

    def unitfield_changed(self):
        su = self.unitfield.read()
        if su:
            self.description.set("{} ({} {}) - updated".format(
                su.name, su.size, su.unit.name))
        else:
            td.s.add(self.item)
            self.description.set("{} ({} {})".format(
                self.item.description, self.item.size,
                self.item.stocktype.unit.name))
        self.update_suggested_price()

    def update_suggested_price(self):
        st = self.typefield.read()
        su = self.unitfield.read()
        if not su:
            td.s.add(self.item)
            su = stocktype.TempStockUnit(
                name=self.item.description,
                size=self.item.size,
                unit=self.item.stocktype.unit)
        cost = self.costfield.f
        if st is None or len(cost) == 0:
            self.suggested_price.set("")
            return
        wholeprice = Decimal(self.costfield.f)
        g = stocktype.PriceGuessHook.guess_price(st, su, wholeprice)
        if g is None:
            self.suggested_price.set("")
        else:
            if isinstance(g, Decimal):
                g = g.quantize(penny)
                self.suggested_price.set("{} per {}".format(
                    tillconfig.fc(g), st.unit.item_name))
            else:
                self.suggested_price.set(g)

    def accept(self):
        td.s.add(self.item)
        st = self.typefield.read()
        if not st:
            ui.infopopup(["You must fill in the stock type field."],
                         title="Error")
            return
        su = self.unitfield.read()
        # If the underlying unit has changed, the unit field must be filled
        # in.  If it hasn't, we can keep the description and size from
        # the unchanged stockitem if required.
        if st.unit != self.item.stocktype.unit:
            if not su:
                ui.infopopup(
                    ["The item size isn't valid for this type of stock.  "
                     "Set a new item size."], title="Error")
                return
        self.dismiss()
        if len(self.costfield.f) == 0:
            self.item.costprice = None
        else:
            self.item.costprice = Decimal(self.costfield.f).quantize(penny)
        if len(self.salefield.f) > 0:
            saleprice = Decimal(self.salefield.f).quantize(penny)
            if st.saleprice != saleprice:
                st.saleprice = saleprice
                st.saleprice_changed = datetime.datetime.now()
        self.item.stocktype = st
        if su:
            self.item.description = su.name
            self.item.size = su.size
        self.item.bestbefore = self.bestbeforefield.read()
        td.s.flush()
        self.func(self.item)

def createsupplier(field, name):
    # Called by the select supplier field if it decides we need to create
    # a new supplier record.
    editsupplier(lambda supplier: field.set(supplier), defaultname=name)

class editsupplier(user.permission_checked, ui.basicpopup):
    permission_required = ('edit-supplier', "Create or edit supplier details")
    def __init__(self, func, supplier=None, defaultname=None):
        if supplier:
            td.s.add(supplier)
        self.func = func
        self.sn = supplier.id if supplier else None
        super().__init__(
            13, 70, title="Supplier Details",
            colour=ui.colour_input, cleartext="Press Clear to go back")
        self.addstr(2, 2, "Please enter the supplier's details. You may ")
        self.addstr(3, 2, "leave the fields other than Name blank if you wish.")
        self.addstr(5, 2, "     Name:")
        self.addstr(6, 2, "Telephone:")
        self.addstr(7, 2, "    Email:")
        self.addstr(8, 2, "      Web:")
        self.namefield = ui.editfield(
            5, 13, 55, flen=60, keymap={
                keyboard.K_CLEAR: (self.dismiss, None)},
            f=supplier.name if supplier else defaultname)
        self.telfield = ui.editfield(
            6, 13, 20, f=supplier.tel if supplier else "")
        self.emailfield = ui.editfield(
            7, 13, 55, flen=60, f=supplier.email if supplier else "")
        self.webfield = ui.editfield(
            8, 13, 55, flen=120, f=supplier.web if supplier else "")
        self.buttonfield = ui.buttonfield(
            10, 28, 10, "Modify" if supplier else "Create",
            keymap={
                keyboard.K_CASH:(self.confirmed, None)})

        ui.map_fieldlist([self.namefield, self.telfield, self.emailfield,
                          self.webfield, self.buttonfield])
        self.namefield.focus()

    def confirmed(self):
        if self.sn:
            supplier = td.s.query(Supplier).get(self.sn)
        else:
            supplier = Supplier()
            td.s.add(supplier)
        supplier.name = self.namefield.f.strip()
        supplier.tel = self.telfield.f.strip()
        supplier.email = self.emailfield.f.strip()
        supplier.web = self.webfield.f.strip()
        try:
            td.s.flush()
        except IntegrityError:
            td.s.rollback()
            ui.infopopup(["There is already a supplier called {}.".format(
                self.namefield.f.strip())], title="Error")
            return
        self.dismiss()
        self.func(supplier)

@user.permission_required('edit-supplier')
def updatesupplier():
    log.info("Update supplier")
    sl = td.s.query(Supplier).order_by(Supplier.name).all()
    m = [(x.name, editsupplier, (lambda a:None, x)) for x in sl]
    ui.menu(m, blurb="Select a supplier from the list and press Cash/Enter.",
            title="Edit Supplier")

@user.permission_required('edit-unit', 'Add or edit a unit')
def edit_unit():
    """Add or edit a unit

    This is a placeholder to ensure the permission is created.
    """
    pass

@user.permission_required('edit-stockunit', 'Add or edit a stock unit')
def edit_stockunit():
    """Add or edit a stockunit

    This is a placeholder to ensure the permission is created.
    """
    pass

class DeliveryHooks(metaclass=InstancePluginMount):
    """Hooks for deliveries

    Accounting integration plugins should subclass this.  Instances of
    subclasses will be called in order of creation.
    """
    def preConfirm(self, deliveryid):
        """Called when a delivery is about to be confirmed.

        To prevent the confirmation taking place, return True.  You
        may pop up your own information box in this case.
        """
        pass
    def confirmed(self, deliveryid):
        """Called when a delivery has been confirmed."""
        pass
