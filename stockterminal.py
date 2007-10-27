import ui,event,time,td,managestock,stock,keyboard,usestock,stocklines
import recordwaste

class page(ui.basicpage):
    def __init__(self,panel):
        ui.basicpage.__init__(self,panel)
        self.display=0
        self.alarm()
        self.redraw()
        event.eventlist.append(self)
    def pagename(self):
        return "Stock Control"
    def drawlines(self):
        sl=td.stockline_summary()
        y=1
        self.win.addstr(0,0,"Line")
        self.win.addstr(0,10,"StockID")
        self.win.addstr(0,18,"Stock")
        self.win.addstr(0,64,"Used")
        self.win.addstr(0,70,"Remaining")
        for name,dept,stockid in sl:
            if dept>3: continue
            self.win.addstr(y,0,name)
            if stockid is not None:
                sd=td.stock_info([stockid])[0]
                self.win.addstr(y,10,"%d"%stockid)
                self.win.addstr(y,18,stock.format_stock(sd,maxw=45))
                self.win.addstr(y,64,"%0.1f"%sd['used'])
                self.win.addstr(y,73,"%0.1f"%sd['remaining'])
            y=y+1
            if y>=(self.h-3): break
    def drawstillage(self):
        sl=td.stillage_summary()
        y=1
        self.win.addstr(0,0,"Loc")
        self.win.addstr(0,5,"StockID")
        self.win.addstr(0,13,"Name")
        self.win.addstr(0,70,"Line")
        for loc,stockid,time,name,line in sl:
            self.win.addstr(y,0,loc[:5])
            self.win.addstr(y,5,"%d"%stockid)
            self.win.addstr(y,13,name)
            if line: self.win.addstr(y,70,line[:9])
            y=y+1
            if y>=(self.h-3): break
    def redraw(self):
        win=self.win
        win.erase()
        win.addstr(self.h-1,0,"Ctrl+X = Clear; Ctrl+Y = Cancel")
        win.addstr(self.h-2,0,"Press S for stock management.  "
                   "Press U to use stock.  Press R to record waste.")
        win.addstr(self.h-3,0,"Press Enter to refresh display.  "
                   "Press A to add a stock annotation.")
        if self.display==0:
            self.drawlines()
        elif self.display==1:
            self.drawstillage()
    def nexttime(self):
        return self.calltime
    def alarm(self):
        self.calltime=time.time()+60.0
        self.display=self.display+1
        if self.display>1: self.display=0
        self.redraw()
    def keypress(self,k):
        if k==keyboard.K_CASH:
            self.alarm()
        elif k==ord('s') or k==ord('S'):
            managestock.popup()
        elif k==ord('a') or k==ord('A'):
            stock.annotate()
        elif k==ord('u') or k==ord('U'):
            stocklines.selectline(usestock.line_chosen,
                                  title="Use Stock",
                                  blurb="Select a stock line",exccap=True)
        elif k==ord('r') or k==ord('R'):
            recordwaste.popup()
        else:
            ui.beep()
