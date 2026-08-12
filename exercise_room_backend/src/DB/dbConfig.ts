import mongoose from "mongoose";

export const dbConfig = async () => {
  try {
    const conn = await mongoose.connect(`${process.env.MONGODB_URI}`);
    console.log(`Mongo DB Connected :Connection host:-`, conn.connection.host);
  } catch (error) {
    console.log(error);
  }
};
