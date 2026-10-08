#include <iostream>
#include <string>
#include "Database.h"
#include "LabSyncService.h"
using namespace std;
int main(){
 string password; cout<<"===== LabSync MySQL Terminal =====\nMySQL root password: ";cin>>password;
 try{Database db("tcp://127.0.0.1:3306","root",password,"labsync");LabSyncService app(db);int role=-1;
  while(role!=0){cout<<"\n1 Student\n2 Admin\n0 Exit\nChoice: ";cin>>role;
   if(role==1){int c=-1;while(c!=0){cout<<"\n--- STUDENT ---\n1 Register\n2 View exams\n3 View slots\n4 Book slot\n5 View my bookings\n6 Cancel booking\n0 Back\nChoice: ";cin>>c;if(c==1)app.registerStudent();else if(c==2)app.listExams();else if(c==3)app.listSlots();else if(c==4)app.bookSlot();else if(c==5)app.myBookings();else if(c==6)app.cancelBooking();}}
   else if(role==2){int c=-1;while(c!=0){cout<<"\n--- ADMIN ---\n1 Add exam + priority\n2 Add slot\n3 Add lab\n4 Add computer\n5 View students\n6 View bookings\n7 Run Priority+FCFS scheduler\n8 View PC availability by slot\n9 Complete session\n0 Back\nChoice: ";cin>>c;if(c==1)app.addExam();else if(c==2)app.addSlot();else if(c==3)app.addLab();else if(c==4)app.addComputer();else if(c==5)app.listStudents();else if(c==6)app.listBookings();else if(c==7)app.runScheduler();else if(c==8)app.computerAvailability();else if(c==9)app.completeSession();}}
  }
}catch(sql::SQLException& e){
    cerr << "\nMySQL Error Code: " << e.getErrorCode() << endl;
    cerr << "SQL State: " << e.getSQLState() << endl;
    cerr << "Error Message: " << e.what() << endl;
    return 1;
}
}
